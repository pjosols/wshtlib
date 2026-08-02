"""Wholeshoot wshtlib - Lambda handler decorators"""

import functools
from typing import Any, Callable

from wshtlib.context import init_context
from wshtlib.logger import get_logger, set_lambda_context

logger = get_logger("wshtlib.decorators")


def bootstrap(fn: Callable[..., Any]) -> Callable[..., Any]:
    """Decorator for synchronously-invoked Lambda entry points (API Gateway).

    Handles warming events (``"source": "lambda-warming"``) — returns 200 early.
    Calls ``init_context`` and ``set_lambda_context`` before invoking the handler.
    Catches unhandled exceptions, logs a structured error, and returns 500.

    Use ``@worker`` instead for asynchronous invocations (S3, EventBridge, SQS),
    where swallowing the exception would suppress retries, destination/DLQ
    routing, and the ``Errors`` metric.

    fn: The Lambda handler function to wrap.
    Returns the wrapped handler with context init, warming, and error handling.
    """

    @functools.wraps(fn)
    def wrapper(event: dict[str, Any], context: Any) -> Any:
        if isinstance(event, dict) and event.get("source") == "lambda-warming":
            return {"statusCode": 200}

        init_context(event, context)
        set_lambda_context(context)

        try:
            return fn(event, context)
        except Exception as exc:
            logger.error(
                "Unhandled exception in %s: %s", fn.__name__, exc, exc_info=True
            )
            return {"statusCode": 500}

    return wrapper


def worker(fn: Callable[..., Any]) -> Callable[..., Any]:
    """Decorator for asynchronously-invoked Lambda entry points.

    For event sources whose return value is discarded — S3, EventBridge, SQS.
    Calls ``init_context`` and ``set_lambda_context`` before invoking the handler,
    logs a structured error on failure, then **re-raises** so Lambda sees the
    invocation as failed: retries, ``on_failure`` destinations, the DLQ, and the
    ``Errors`` metric all depend on the exception propagating.

    No warming-event handling — warming targets synchronous handlers only.

    fn: The Lambda handler function to wrap.
    Returns the wrapped handler with context init and error logging.
    """

    @functools.wraps(fn)
    def wrapper(event: dict[str, Any], context: Any) -> Any:
        init_context(event, context)
        set_lambda_context(context)

        try:
            return fn(event, context)
        except Exception as exc:
            logger.error(
                "Unhandled exception in %s: %s", fn.__name__, exc, exc_info=True
            )
            raise

    return wrapper
