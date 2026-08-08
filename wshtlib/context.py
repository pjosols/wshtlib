"""Request-scoped context store using contextvars."""

import os
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


def set_service(service: Optional[str]) -> None:
    """Set the service name in the current context.

    service: Logical service identifier, shared by logging and metrics.
    """
    ctx = dict(_ctx.get())
    ctx["service"] = service
    _ctx.set(ctx)


def resolve_service(explicit: Optional[str] = None) -> Optional[str]:
    """Resolve the service name from the first source that supplies one.

    Order: ``explicit``, the current context (see ``set_service``),
    ``WSHT_SERVICE_NAME``, then Lambda's own ``AWS_LAMBDA_FUNCTION_NAME``.
    Logging and metrics both resolve through here, so a log line and a metric
    emitted from the same context report the same service.

    explicit: Caller-supplied name, taking precedence over every other source.
    Returns the resolved service name, or ``None`` if no source supplies one.
    """
    return (
        explicit
        or _ctx.get().get("service")
        or os.getenv("WSHT_SERVICE_NAME")
        or os.getenv("AWS_LAMBDA_FUNCTION_NAME")
        or None
    )


def clear_context() -> None:
    """Reset context to empty dict (useful in tests)."""
    _ctx.set({})
