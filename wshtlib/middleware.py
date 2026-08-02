"""Initialise request context and log HTTP requests in FastAPI/Starlette."""

import time
from typing import Any, Awaitable, Callable

from wshtlib.context import get_context, init_context_from_request
from wshtlib.logger import get_logger

_logger = get_logger("wshtlib.middleware")

try:
    from starlette.middleware.base import BaseHTTPMiddleware
    from starlette.requests import Request
    from starlette.responses import Response

    class WshtlibMiddleware(BaseHTTPMiddleware):
        """Initialise request context, log summary, inject X-Trace-Id header."""

        async def dispatch(
            self,
            request: Request,
            call_next: Callable[[Request], Awaitable[Response]],
        ) -> Response:
            """Process request: init context, call handler, log, add trace header.

            request: The incoming Starlette/FastAPI request.
            call_next: ASGI next-middleware callable.
            Returns the response with X-Trace-Id header if a trace_id is present.
            """
            init_context_from_request(request)
            start = time.monotonic()
            response: Response = await call_next(request)
            duration_ms = round((time.monotonic() - start) * 1000)
            ctx = get_context()
            trace_id: Any = ctx.get("trace_id")
            _logger.info(
                "request",
                method=request.method,
                path=request.url.path,
                status=response.status_code,
                duration_ms=duration_ms,
            )
            if trace_id:
                response.headers["X-Trace-Id"] = trace_id
            return response

except ImportError:
    # FastAPI/Starlette is an optional dependency — skip class definition gracefully
    # when the package is not installed.
    pass
