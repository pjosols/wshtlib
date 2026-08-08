"""Emit structured JSON logs to stdout with runtime and Lambda context enrichment."""

import json
import logging
import os
import socket
import threading
from datetime import datetime, timezone
from typing import Any, Mapping, Optional, Union

from wshtlib.context import get_context, resolve_service

_cold_start = True

# The invocation's Lambda fields, held once for the process rather than once
# per logger. A Lambda context describes the process, so every logger reports
# the same one -- including a logger built after the invocation began, which
# would otherwise carry none of these fields at all.
_lambda_fields: dict[str, Any] = {}

# Guards the logger registry against a concurrent get_logger for the same name.
_registry_lock = threading.Lock()


def _detect_runtime() -> dict[str, Any]:
    """Return static enrichment fields based on the detected runtime environment.

    Returns a dict with runtime-specific fields (no sensitive data).
    """
    if os.getenv("AWS_LAMBDA_FUNCTION_NAME"):
        return {"runtime": "lambda"}
    if os.getenv("ECS_CONTAINER_METADATA_URI_V4"):
        return {"runtime": "ecs"}
    return {"runtime": "local", "hostname": socket.gethostname(), "pid": os.getpid()}


_RUNTIME_FIELDS: dict[str, Any] = _detect_runtime()

# Keys the formatter owns. A caller field with one of these names is emitted
# under an "extra_" prefix instead: overwriting them would let an enrichment
# field falsify the record it was meant to enrich -- an INFO line indexed as
# DEBUG, a fabricated timestamp, the wrong service, a broken trace correlation.
_RESERVED_KEYS = frozenset(
    {
        "level",
        "location",
        "message",
        "timestamp",
        "service",
        "logger",
        "trace_id",
        "exception",
        "runtime",
        "hostname",
        "pid",
        "function_name",
        "function_arn",
        "function_memory_size",
        "function_request_id",
        "cold_start",
    }
)

# Attribute names stdlib's LogRecord already uses. Caller fields are mirrored
# onto the record so custom filters, %(field)s formatters, and handlers that
# harvest record.__dict__ keep working -- but not these, which would trip
# stdlib's reserved-name check and raise KeyError at the call site.
_RECORD_ATTRS = frozenset(
    {
        "args",
        "asctime",
        "created",
        "exc_info",
        "exc_text",
        "filename",
        "funcName",
        "levelname",
        "levelno",
        "lineno",
        "message",
        "module",
        "msecs",
        "msg",
        "name",
        "pathname",
        "process",
        "processName",
        "relativeCreated",
        "stack_info",
        "taskName",
        "thread",
        "threadName",
    }
)


class _JsonFormatter(logging.Formatter):
    def _get_trace_id(self) -> Optional[str]:
        trace_id = get_context().get("trace_id")
        return str(trace_id) if trace_id else None

    def _get_service(self, record: logging.LogRecord) -> str:
        """Resolve the service name, falling back to the logger's own name.

        Shares ``resolve_service`` with metrics so both report the same value;
        ``record.name`` is the tail, used only where nothing else supplies one.
        No per-record override is offered: ``service`` is a reserved key, so
        ``_emit`` strips it before it can reach the record.

        record: The log record being formatted.
        """
        return resolve_service() or record.name

    def format(self, record: logging.LogRecord) -> str:
        entry: dict[str, Any] = {
            "level": record.levelname,
            "location": f"{record.funcName}:{record.lineno}",
            "message": record.getMessage(),
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "service": self._get_service(record),
            "logger": record.name,
        }
        entry.update(_RUNTIME_FIELDS)
        entry.update(_lambda_fields)
        trace_id = self._get_trace_id()
        if trace_id:
            entry["trace_id"] = trace_id
        if record.exc_info and record.exc_info[0] is not None:
            entry["exception"] = self.formatException(record.exc_info)
        fields = getattr(record, "_extra_keys", None)
        if fields:
            for key, value in fields.items():
                entry[f"extra_{key}" if key in _RESERVED_KEYS else key] = value
        return json.dumps(entry, default=str)


_ExcInfo = Union[
    bool,
    tuple[type[BaseException], BaseException, Any],
    tuple[None, None, None],
    BaseException,
    None,
]


class _Logger(logging.Logger):
    """Logger accepting structured fields as keyword arguments.

    ``logger.info("user signed in", user_id="u_123")`` and stdlib's
    ``extra={...}`` both land in the same JSON entry; keyword arguments win a
    key collision. Fields colliding with a name the formatter owns are emitted
    with an ``extra_`` prefix rather than replacing it.

    ``exc_info``, ``extra``, ``stack_info``, and ``stacklevel`` keep their
    stdlib meanings and cannot be used as field names. Every other name is
    available, including ``msg``, ``args``, and ``level``.
    """

    def __init__(self, name: str, level: int = logging.NOTSET) -> None:
        super().__init__(name, level)
        self._formatter = _JsonFormatter()
        handler = logging.StreamHandler()
        handler.setFormatter(self._formatter)
        self.addHandler(handler)
        self.propagate = False

    def set_lambda_context(self, context: object) -> None:
        """Record the invocation's Lambda context for every logger in the process."""
        set_lambda_context(context)

    def _emit(
        self,
        level: int,
        msg: object,
        args: tuple[object, ...],
        exc_info: _ExcInfo,
        extra: Optional[Mapping[str, object]],
        stack_info: bool,
        stacklevel: int,
        fields: dict[str, Any],
    ) -> None:
        if not self.isEnabledFor(level):
            return
        merged: dict[str, Any] = dict(extra) if extra else {}
        # Keyword arguments win a collision: they are this library's spelling.
        merged.update(fields)
        payload: Optional[dict[str, Any]] = None
        if merged:
            payload = {
                k: v
                for k, v in merged.items()
                if k not in _RECORD_ATTRS and k not in _RESERVED_KEYS
            }
            payload["_extra_keys"] = merged
        # +2 skips this frame and the public method that called it, so
        # `location` resolves to the caller rather than to wshtlib itself.
        super()._log(
            level,
            msg,
            args,
            exc_info=exc_info,
            extra=payload,
            stack_info=stack_info,
            stacklevel=stacklevel + 2,
        )

    # The seven methods below differ only in a level constant, and the
    # repetition is load-bearing: these explicit signatures are what make
    # `logger.info("event", field=1)` type-check under mypy strict. Collapsing
    # them into a factory or partialmethod erases the typed keyword spelling
    # this library documents, which 0.3.0 added deliberately.
    def debug(  # type: ignore[override]
        self,
        msg: object,
        /,
        *args: object,
        exc_info: _ExcInfo = None,
        extra: Optional[Mapping[str, object]] = None,
        stack_info: bool = False,
        stacklevel: int = 1,
        **fields: Any,
    ) -> None:
        self._emit(
            logging.DEBUG, msg, args, exc_info, extra, stack_info, stacklevel, fields
        )

    def info(  # type: ignore[override]
        self,
        msg: object,
        /,
        *args: object,
        exc_info: _ExcInfo = None,
        extra: Optional[Mapping[str, object]] = None,
        stack_info: bool = False,
        stacklevel: int = 1,
        **fields: Any,
    ) -> None:
        self._emit(
            logging.INFO, msg, args, exc_info, extra, stack_info, stacklevel, fields
        )

    def warning(  # type: ignore[override]
        self,
        msg: object,
        /,
        *args: object,
        exc_info: _ExcInfo = None,
        extra: Optional[Mapping[str, object]] = None,
        stack_info: bool = False,
        stacklevel: int = 1,
        **fields: Any,
    ) -> None:
        self._emit(
            logging.WARNING, msg, args, exc_info, extra, stack_info, stacklevel, fields
        )

    def error(  # type: ignore[override]
        self,
        msg: object,
        /,
        *args: object,
        exc_info: _ExcInfo = None,
        extra: Optional[Mapping[str, object]] = None,
        stack_info: bool = False,
        stacklevel: int = 1,
        **fields: Any,
    ) -> None:
        self._emit(
            logging.ERROR, msg, args, exc_info, extra, stack_info, stacklevel, fields
        )

    def critical(  # type: ignore[override]
        self,
        msg: object,
        /,
        *args: object,
        exc_info: _ExcInfo = None,
        extra: Optional[Mapping[str, object]] = None,
        stack_info: bool = False,
        stacklevel: int = 1,
        **fields: Any,
    ) -> None:
        self._emit(
            logging.CRITICAL, msg, args, exc_info, extra, stack_info, stacklevel, fields
        )

    def exception(  # type: ignore[override]
        self,
        msg: object,
        /,
        *args: object,
        exc_info: _ExcInfo = True,
        extra: Optional[Mapping[str, object]] = None,
        stack_info: bool = False,
        stacklevel: int = 1,
        **fields: Any,
    ) -> None:
        self._emit(
            logging.ERROR, msg, args, exc_info, extra, stack_info, stacklevel, fields
        )

    def log(  # type: ignore[override]
        self,
        level: int,
        msg: object,
        /,
        *args: object,
        exc_info: _ExcInfo = None,
        extra: Optional[Mapping[str, object]] = None,
        stack_info: bool = False,
        stacklevel: int = 1,
        **fields: Any,
    ) -> None:
        self._emit(level, msg, args, exc_info, extra, stack_info, stacklevel, fields)


def _resolve_level(raw: Optional[str]) -> int:
    """Translate a configured level into a logging level number.

    ``setLevel`` rejects anything outside its own name table, and ``get_logger``
    runs at import in this package -- so a variable declared but left blank, or
    spelled in lowercase, would otherwise raise ValueError and take down
    ``import wshtlib`` before the first line was ever logged. An unusable value
    leaves the default in place instead.

    raw: The configured value, typically ``WSHT_LOG_LEVEL``.
    Returns a level number, defaulting to INFO.
    """
    if not raw:
        return logging.INFO
    name = raw.strip().upper()
    if name.isdigit():
        return int(name)
    level = logging.getLevelName(name)
    # getLevelName returns the string "Level BOGUS" for a name it does not know.
    return level if isinstance(level, int) else logging.INFO


def get_logger(service_name: str) -> "_Logger":
    """Get a structured JSON logger for the given service.

    service_name: Logger name / service identifier.
    Returns a _Logger instance (created or retrieved from the logging registry).
    """
    with _registry_lock:
        existing = logging.Logger.manager.loggerDict.get(service_name)
        if isinstance(existing, _Logger):
            return existing
        logger = _Logger(service_name)
        logger.setLevel(_resolve_level(os.getenv("WSHT_LOG_LEVEL")))
        logging.Logger.manager.loggerDict[service_name] = logger
        return logger


def set_lambda_context(context: object) -> None:
    """Record the invocation's Lambda context for every logger in the process.

    ``cold_start`` belongs to the invocation, not to whichever logger happened
    to be told about it first: the fields are held once, module-side, so every
    logger reports the same values and a logger created later still gets them.

    context: The Lambda context object.
    """
    global _cold_start, _lambda_fields
    _lambda_fields = {
        "function_name": getattr(context, "function_name", None),
        "function_arn": getattr(context, "invoked_function_arn", None),
        "function_memory_size": getattr(context, "memory_limit_in_mb", None),
        "function_request_id": getattr(context, "aws_request_id", None),
        "cold_start": _cold_start,
    }
    _cold_start = False
