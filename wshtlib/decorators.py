"""Wholeshoot wshtlib - Lambda handler decorator"""

import functools
from typing import Any, Callable

from wshtlib.context import init_context
from wshtlib.logger import get_logger, set_lambda_context

logger = get_logger("wshtlib.decorators")


def bootstrap(fn: Callable[..., Any]) -> Callable[..., Any]:
    """Decorator for Lambda entry points.

    Handles warming events (``"source": "lambda-warming"``) — returns 200 early.
    Calls ``init_context`` and ``set_lambda_context`` before invoking the handler.
    Catches unhandled exceptions, logs a structured error, and returns 500.

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
