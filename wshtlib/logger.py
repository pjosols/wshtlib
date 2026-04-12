"""Wholeshoot shared structured JSON logger"""

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
            # Broad except is intentional: trace injection is best-effort and
            # must never crash the formatter regardless of import or runtime errors.
            from wshtlib.context import get_context

            return get_context().get("trace_id")
        except Exception:  # noqa: BLE001
            return None

    def format(self, record: logging.LogRecord) -> str:
        entry: dict[str, Any] = {
            "level": record.levelname,
            "location": f"{record.funcName}:{record.lineno}",
            "message": record.getMessage(),
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "service": getattr(record, "service", record.name),
        }
        entry.update(_RUNTIME_FIELDS)
        entry.update(self._lambda_context)
        trace_id = self._get_trace_id()
        if trace_id:
            entry["trace_id"] = trace_id
        if hasattr(record, "_extra_keys"):
            entry.update(record._extra_keys)
        if record.exc_info and record.exc_info[0] is not None:
            entry["exception"] = self.formatException(record.exc_info)
        return json.dumps(entry, default=str)


_ExcInfo = Union[
    bool,
    tuple[type[BaseException], BaseException, Any],
    tuple[None, None, None],
    BaseException,
    None,
]


class _Logger(logging.Logger):
    def __init__(self, name: str, level: int = logging.NOTSET) -> None:
        super().__init__(name, level)
        self._formatter = _JsonFormatter()
        handler = logging.StreamHandler()
        handler.setFormatter(self._formatter)
        self.addHandler(handler)
        self.propagate = False

    def set_lambda_context(self, context: object) -> None:
        self._formatter.set_lambda_context(context)

    def _log(
        self,
        level: int,
        msg: object,
        args: Union[tuple[object, ...], Mapping[str, object]],
        exc_info: _ExcInfo = None,
        extra: Optional[Mapping[str, object]] = None,
        stack_info: bool = False,
        stacklevel: int = 1,
        **kwargs: Any,
    ) -> None:
        if kwargs:
            merged: dict[str, object] = dict(extra) if extra else {}
            merged["_extra_keys"] = kwargs
            extra = merged
        super()._log(
            level,
            msg,
            args,
            exc_info=exc_info,
            extra=extra,
            stack_info=stack_info,
            stacklevel=stacklevel,
        )


def get_logger(service_name: str) -> "_Logger":
    """Get a structured JSON logger for the given service.

    service_name: Logger name / service identifier.
    Returns a _Logger instance (created or retrieved from the logging registry).
    """
    existing = logging.Logger.manager.loggerDict.get(service_name)
    if isinstance(existing, _Logger):
        return existing
    logger = _Logger(service_name)
    logger.setLevel(os.getenv("LOG_LEVEL", "INFO"))
    logging.Logger.manager.loggerDict[service_name] = logger
    return logger


def set_lambda_context(context: object) -> None:
    """Propagate Lambda context to all active wshtlib loggers.

    context: The Lambda context object.
    """
    for logger in logging.Logger.manager.loggerDict.values():
        if isinstance(logger, _Logger):
            logger.set_lambda_context(context)
