"""Emit structured JSON logs to stdout with runtime and Lambda context enrichment."""

import json
import logging
import os
import socket
from datetime import datetime, timezone
from typing import Any, Mapping, Optional, Union

_cold_start = True


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
    def __init__(self) -> None:
        super().__init__()
        self._lambda_context: dict[str, Any] = {}

    def set_lambda_context(self, context: object) -> None:
        global _cold_start
        self._lambda_context = {
            "function_name": getattr(context, "function_name", None),
            "function_arn": getattr(context, "invoked_function_arn", None),
            "function_memory_size": getattr(context, "memory_limit_in_mb", None),
            "function_request_id": getattr(context, "aws_request_id", None),
            "cold_start": _cold_start,
        }
        _cold_start = False

    def _get_trace_id(self) -> Optional[str]:
        try:
            # Lazy import avoids circular dependency with wshtlib.context.
            from wshtlib.context import get_context

            return get_context().get("trace_id")
        except (ImportError, AttributeError):
            return None

    def _get_service(self, record: logging.LogRecord) -> str:
        """Resolve the service name, falling back to the logger's own name.

        Shares ``resolve_service`` with metrics so both report the same value;
        ``record.name`` is the tail, used only where nothing else supplies one.

        record: The log record being formatted.
        """
        try:
            # Lazy import avoids circular dependency with wshtlib.context.
            from wshtlib.context import resolve_service

            resolved = resolve_service(getattr(record, "service", None))
        except (ImportError, AttributeError):
            resolved = getattr(record, "service", None)
        return resolved or record.name

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
        entry.update(self._lambda_context)
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
        self._formatter.set_lambda_context(context)

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


def get_logger(service_name: str) -> "_Logger":
    """Get a structured JSON logger for the given service.

    service_name: Logger name / service identifier.
    Returns a _Logger instance (created or retrieved from the logging registry).
    """
    existing = logging.Logger.manager.loggerDict.get(service_name)
    if isinstance(existing, _Logger):
        return existing
    logger = _Logger(service_name)
    logger.setLevel(os.getenv("WSHT_LOG_LEVEL", "INFO"))
    logging.Logger.manager.loggerDict[service_name] = logger
    return logger


def set_lambda_context(context: object) -> None:
    """Propagate Lambda context to all active wshtlib loggers.

    context: The Lambda context object.
    """
    for logger in logging.Logger.manager.loggerDict.values():
        if isinstance(logger, _Logger):
            logger.set_lambda_context(context)
