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
            try:
                response: Response = await call_next(request)
            except Exception:
                # Without this the failing request -- the one most worth having
                # in the access log -- produced no line at all. Re-raised
                # rather than answered here: returning a response would
                # pre-empt the application's own exception handlers. The trace
                # header cannot follow on this path, there being no response to
                # put it on.
                self._log(request, 500, start, failed=True)
                raise
            self._log(request, response.status_code, start)
            ctx = get_context()
            trace_id: Any = ctx.get("trace_id")
            if trace_id:
                response.headers["X-Trace-Id"] = trace_id
            return response

        def _log(
            self, request: Request, status: int, start: float, failed: bool = False
        ) -> None:
            """Emit the access-log line for a finished request.

            request: The request being logged.
            status: Status code to record; 500 where the handler raised.
            start: ``time.monotonic()`` reading from before the handler ran.
            failed: True if the handler raised, which logs at error with a
                traceback rather than at info.
            """
            fields: dict[str, Any] = {
                "method": request.method,
                "path": request.url.path,
                "status": status,
                "duration_ms": round((time.monotonic() - start) * 1000),
            }
            if failed:
                _logger.error("request", exc_info=True, **fields)
            else:
                _logger.info("request", **fields)

except ImportError:
    # FastAPI/Starlette is an optional dependency — skip class definition gracefully
    # when the package is not installed.
    pass
