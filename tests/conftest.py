"""Shared test helpers for wshtlib test suite."""

import json
import logging
from io import StringIO
from unittest.mock import MagicMock

from wshtlib.logger import _Logger


def capture_log(log_fn, *args, **kwargs) -> dict:
    """Invoke a logger method and return the parsed JSON entry.

    log_fn: Bound logger method (e.g., logger.info).
    *args, **kwargs: Arguments to pass to log_fn.
    Returns the parsed JSON log entry as a dict.
    Raises AttributeError if log_fn is not a bound _Logger method.
    Raises json.JSONDecodeError if the emitted output is not valid JSON.
    """
    buf = StringIO()
    handler = logging.StreamHandler(buf)
    handler.setFormatter(log_fn.__self__._formatter)
    log_fn.__self__.handlers = [handler]
    log_fn(*args, **kwargs)
    return json.loads(buf.getvalue().strip())


def fresh_logger(name: str = "test-svc") -> _Logger:
    """Create a new _Logger instance, bypassing the registry cache.

    name: Logger name. Defaults to "test-svc".
    Returns a _Logger with DEBUG level.
    """
    lg = _Logger(name)
    lg.setLevel(logging.DEBUG)
    return lg


def make_lambda_context(**kwargs) -> MagicMock:
    """Create a mock Lambda context object with specified attributes.

    **kwargs: Attributes to set (function_name, arn, memory, request_id).
    Returns a MagicMock with Lambda context attributes.
    """
    ctx = MagicMock()
    ctx.function_name = kwargs.get("function_name", "my-lambda")
    ctx.invoked_function_arn = kwargs.get(
        "arn", "arn:aws:lambda:us-west-2:123:function:my-lambda"
    )
    ctx.memory_limit_in_mb = kwargs.get("memory", "256")
    ctx.aws_request_id = kwargs.get("request_id", "req-abc-123")
    return ctx


def emit_with_lambda_context(ctx: MagicMock) -> dict:
    """Log a message with Lambda context set and return the parsed JSON entry.

    ctx: Lambda context object.
    Returns the parsed JSON log entry as a dict.
    """
    lg = fresh_logger("lambda-svc")
    lg.set_lambda_context(ctx)
    buf = StringIO()
    handler = logging.StreamHandler(buf)
    handler.setFormatter(lg._formatter)
    lg.handlers = [handler]
    lg.info("lambda log")
    return json.loads(buf.getvalue().strip())
