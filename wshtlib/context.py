"""Wholeshoot wshtlib - request-scoped context store using contextvars"""

from contextvars import ContextVar
from typing import Any, Optional

_ctx: ContextVar[dict[str, Any]] = ContextVar("_wshtlib_ctx", default={})


def init_context(event: dict[str, Any], lambda_context: Any) -> None:
    """Initialise context from a Lambda event and context object.

    event: The Lambda event dict (API Gateway or direct invocation).
    lambda_context: The Lambda context object.
    """
    trace_id = (event.get("headers", {}) or {}).get("x-amzn-trace-id") or (
        event.get("requestContext", {}) or {}
    ).get("requestId")
    _ctx.set(
        {
            "trace_id": trace_id,
            "correlation_id": getattr(lambda_context, "aws_request_id", None),
            "user_id": None,
        }
    )


def init_context_from_request(request: Any) -> None:
    """Initialise context from a FastAPI/ASGI Request object.

    request: A Starlette/FastAPI Request instance.
    """
    trace_id = request.headers.get("x-amzn-trace-id")
    correlation_id = request.headers.get("x-correlation-id") or str(
        request.scope.get("path", "")
    )
    _ctx.set(
        {
            "trace_id": trace_id,
            "correlation_id": correlation_id,
            "user_id": None,
        }
    )


def get_context() -> dict[str, Any]:
    """Return the current request-scoped context dict."""
    return dict(_ctx.get())


def set_user_id(user_id: Optional[str]) -> None:
    """Set the user_id in the current context.

    user_id: The authenticated user's sub/ID.
    """
    ctx = dict(_ctx.get())
    ctx["user_id"] = user_id
    _ctx.set(ctx)


def clear_context() -> None:
    """Reset context to empty dict (useful in tests)."""
    _ctx.set({})
