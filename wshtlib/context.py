"""Request-scoped context store using contextvars."""

import os
import uuid
from contextvars import ContextVar
from typing import Any, Optional

# The default is None rather than a shared ``{}``: a mutable default is one
# in-place ``_ctx.get()["k"] = v`` away from poisoning every context in the
# process, including those of unrelated threads.
_ctx: ContextVar[Optional[dict[str, Any]]] = ContextVar("_wshtlib_ctx", default=None)

_TRACE_HEADER = "x-amzn-trace-id"
_CORRELATION_HEADER = "x-correlation-id"


def _current() -> dict[str, Any]:
    """Return the context dict currently installed, empty if there is none."""
    return _ctx.get() or {}


def _replace(**fields: Any) -> None:
    """Install a fresh context for a new request, carrying ``service`` across.

    ``service`` names the deployment rather than the request, and a caller sets
    it once during initialisation. Dropping it here would make ``set_service``
    silently dead under ``@bootstrap`` and ``@worker``, which start a new
    context on every invocation.
    """
    service = _current().get("service")
    if service is not None:
        fields["service"] = service
    _ctx.set(fields)


def _update(**fields: Any) -> None:
    """Merge fields into the current context, leaving the rest in place."""
    _ctx.set({**_current(), **fields})


def _header(headers: Any, name: str) -> Optional[str]:
    """Return a header value by case-insensitive name, or None.

    API Gateway's HTTP API (v2) lowercases header names, but REST API (v1) and
    ALB pass them through with the client's own casing — so an exact-match
    lookup finds the X-Ray header on one integration out of three.

    headers: The event's ``headers`` mapping, which may be absent or null.
    name: Lowercase header name to look for.
    """
    if not isinstance(headers, dict):
        return None
    for key, value in headers.items():
        if isinstance(key, str) and key.lower() == name and value is not None:
            return str(value)
    return None


def init_context(event: dict[str, Any], lambda_context: Any) -> None:
    """Initialise context from a Lambda event and context object.

    event: The Lambda event dict (API Gateway or direct invocation).
    lambda_context: The Lambda context object.
    """
    trace_id = (
        _header(event.get("headers"), _TRACE_HEADER)
        # Lambda exports the active X-Ray header here on every invocation,
        # including event sources that carry no HTTP headers at all.
        or os.getenv("_X_AMZN_TRACE_ID")
        or (event.get("requestContext") or {}).get("requestId")
    )
    _replace(
        trace_id=trace_id,
        correlation_id=getattr(lambda_context, "aws_request_id", None),
        user_id=None,
    )


def init_context_from_request(request: Any) -> None:
    """Initialise context from a FastAPI/ASGI Request object.

    request: A Starlette/FastAPI Request instance.
    """
    # Starlette's Headers mapping is already case-insensitive.
    trace_id = request.headers.get(_TRACE_HEADER)
    # A generated id rather than the request path: correlation exists to single
    # out one request, and every call to /health sharing the id "/health" makes
    # the field worse than absent.
    correlation_id = request.headers.get(_CORRELATION_HEADER) or str(uuid.uuid4())
    _replace(trace_id=trace_id, correlation_id=correlation_id, user_id=None)


def get_context() -> dict[str, Any]:
    """Return the current request-scoped context dict."""
    return dict(_current())


def set_user_id(user_id: Optional[str]) -> None:
    """Set the user_id in the current context.

    user_id: The authenticated user's sub/ID.
    """
    _update(user_id=user_id)


def set_service(service: Optional[str]) -> None:
    """Set the service name in the current context.

    Initialisation-time configuration, not per-request data. Two consequences
    follow from contextvars, and ``WSHT_SERVICE_NAME`` is the remedy for both:

    * A context set on one thread is invisible on another — a new thread starts
      from an empty context, never a copy. Under Starlette that covers ``def``
      endpoints run in the threadpool and anything under ``TestClient``. A call
      from a FastAPI lifespan or startup handler is likewise unreachable from
      request tasks, which are not its children.
    * On a warm Lambda container the value now survives into later invocations,
      since ``init_context`` deliberately carries it across.

    service: Logical service identifier, shared by logging and metrics.
    """
    _update(service=service)


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
        or _current().get("service")
        or os.getenv("WSHT_SERVICE_NAME")
        or os.getenv("AWS_LAMBDA_FUNCTION_NAME")
        or None
    )


def clear_context() -> None:
    """Reset context to empty, including the service name (useful in tests)."""
    _ctx.set(None)
