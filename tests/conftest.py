"""Shared test helpers for wshtlib test suite."""

import json
import logging
import os
from collections.abc import Iterator
from io import StringIO
from pathlib import Path
from unittest.mock import MagicMock

import pytest

import wshtlib.logger as logger_module
from wshtlib.logger import _Logger

# The JSON Schema published in the CloudWatch embedded metric format
# specification. Validating against it checks the output against AWS's
# definition rather than against our own idea of what we emit. Copied verbatim
# but for an added "$schema": AWS omits it, and without the draft-07 declaration
# its own "$id" fragments are rejected by newer drafts.
EMF_SCHEMA = json.loads((Path(__file__).parent / "emf_schema.json").read_text())

# Every environment variable that steers wshtlib. The service chain ends at
# AWS_LAMBDA_FUNCTION_NAME, so a developer machine or CI job that happens to
# export one of these would change the result of tests that never mention it.
_WSHTLIB_ENV_VARS = (
    "WSHT_LOG_LEVEL",
    "WSHT_ENVIRONMENT",
    "WSHT_METRICS_NAMESPACE",
    "WSHT_SERVICE_NAME",
    "WSHT_SECRET_CACHE_TTL",
    "AWS_LAMBDA_FUNCTION_NAME",
    # Lambda exports this on every invocation, and init_context reads it as a
    # trace-id source -- so a test running inside Lambda-like tooling would
    # otherwise see a trace id it never set.
    "_X_AMZN_TRACE_ID",
)


@pytest.fixture(autouse=True)
def isolate_wshtlib_env() -> Iterator[None]:
    """Clear wshtlib's environment variables around every test.

    Deliberately does not use ``monkeypatch``: requesting it from an autouse
    fixture drags its setup earlier, which pushes its undo past xunit-style
    ``teardown_method`` and breaks tests that patch ``sys.modules``.
    """
    saved = {key: os.environ.pop(key) for key in _WSHTLIB_ENV_VARS if key in os.environ}
    try:
        yield
    finally:
        os.environ.update(saved)


@pytest.fixture(autouse=True)
def reset_lambda_fields() -> Iterator[None]:
    """Forget the invocation's Lambda fields around every test.

    They are module state by design -- a Lambda context describes the process,
    not one logger -- which means one test's mock context would otherwise go on
    enriching the log lines of every test that ran after it.
    """
    logger_module._lambda_fields = {}
    logger_module._cold_start = True
    yield
    logger_module._lambda_fields = {}
    logger_module._cold_start = True


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
