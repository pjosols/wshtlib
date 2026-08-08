"""Test FastAPI request context and logging middleware."""

import io
import json
import logging
from collections.abc import Callable, Generator

import pytest
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route
from starlette.testclient import TestClient

from wshtlib.context import clear_context, get_context
from wshtlib.middleware import WshtlibMiddleware


@pytest.fixture(autouse=True)
def reset_context() -> Generator[None, None, None]:
    clear_context()
    yield
    clear_context()


def _make_app() -> Starlette:
    async def ping(request: Request) -> JSONResponse:
        return JSONResponse({"ok": True})

    async def status(request: Request) -> JSONResponse:
        return JSONResponse({"status": "ok"})

    app = Starlette(routes=[Route("/ping", ping), Route("/status", status)])
    app.add_middleware(WshtlibMiddleware)
    return app


def _capture_log_entry(fn: Callable[[], None]) -> dict[str, object]:
    """Run fn() and return the last JSON log entry from wshtlib.middleware logger."""
    buf = io.StringIO()
    mw_logger = logging.getLogger("wshtlib.middleware")
    # Reuse the existing formatter so output is JSON, not bare message strings
    existing_formatter = mw_logger.handlers[0].formatter if mw_logger.handlers else None
    handler = logging.StreamHandler(buf)
    if existing_formatter:
        handler.setFormatter(existing_formatter)
    mw_logger.addHandler(handler)
    try:
        fn()
    finally:
        mw_logger.removeHandler(handler)
    lines = [line for line in buf.getvalue().strip().splitlines() if line]
    return json.loads(lines[-1])


# --- X-Trace-Id header injection ---


def test_trace_id_injected_into_response_header() -> None:
    client = TestClient(_make_app())
    resp = client.get("/ping", headers={"x-amzn-trace-id": "Root=1-abc"})
    assert resp.status_code == 200
    assert resp.headers["x-trace-id"] == "Root=1-abc"


def test_no_trace_id_header_when_not_in_request() -> None:
    client = TestClient(_make_app())
    resp = client.get("/ping")
    assert resp.status_code == 200
    assert "x-trace-id" not in resp.headers


# --- context is initialised per request ---


def test_context_populated_during_request() -> None:
    """Context is set inside the request thread — verify via response body."""

    async def ctx_endpoint(request: Request) -> JSONResponse:
        return JSONResponse(get_context())

    app = Starlette(routes=[Route("/ctx", ctx_endpoint)])
    app.add_middleware(WshtlibMiddleware)

    client = TestClient(app)
    resp = client.get(
        "/ctx",
        headers={"x-amzn-trace-id": "Root=1-test", "x-correlation-id": "corr-99"},
    )
    body = resp.json()
    assert body["trace_id"] == "Root=1-test"
    assert body["correlation_id"] == "corr-99"
    assert body["user_id"] is None


# --- request logging ---


def test_request_is_logged() -> None:
    client = TestClient(_make_app())
    entry = _capture_log_entry(lambda: client.get("/ping"))
    assert entry["message"] == "request"
    assert entry["method"] == "GET"
    assert entry["path"] == "/ping"
    assert isinstance(entry["status"], int)
    assert isinstance(entry["duration_ms"], int)


def test_log_includes_correct_status_code() -> None:
    client = TestClient(_make_app())
    entry = _capture_log_entry(lambda: client.get("/status"))
    assert entry["status"] == 200


def test_log_includes_correct_method() -> None:
    async def create(request: Request) -> JSONResponse:
        return JSONResponse({})

    app = Starlette(routes=[Route("/items", create, methods=["POST"])])
    app.add_middleware(WshtlibMiddleware)

    client = TestClient(app)
    entry = _capture_log_entry(lambda: client.post("/items"))
    assert entry["method"] == "POST"


# --- response body is preserved ---


def test_response_body_unchanged() -> None:
    client = TestClient(_make_app())
    resp = client.get("/ping")
    assert resp.json() == {"ok": True}


# --- a handler that raises ---


def _make_failing_app() -> Starlette:
    async def boom(request: Request) -> JSONResponse:
        raise RuntimeError("kaboom")

    app = Starlette(routes=[Route("/boom", boom)])
    app.add_middleware(WshtlibMiddleware)
    return app


def test_failing_request_is_still_logged() -> None:
    """The request most worth having in the access log produced no line at all."""
    client = TestClient(_make_failing_app(), raise_server_exceptions=False)
    entry = _capture_log_entry(lambda: client.get("/boom"))

    assert entry["message"] == "request"
    assert entry["path"] == "/boom"
    assert entry["status"] == 500
    assert entry["level"] == "ERROR"
    assert isinstance(entry["duration_ms"], int)


def test_failing_request_log_carries_the_traceback() -> None:
    client = TestClient(_make_failing_app(), raise_server_exceptions=False)
    entry = _capture_log_entry(lambda: client.get("/boom"))

    assert "kaboom" in str(entry["exception"])


def test_the_exception_still_propagates() -> None:
    """Answering the request here would pre-empt the app's own handlers."""
    client = TestClient(_make_failing_app())
    with pytest.raises(RuntimeError, match="kaboom"):
        client.get("/boom")


# --- WshtlibMiddleware is importable ---


def test_middleware_class_exists() -> None:
    from wshtlib.middleware import WshtlibMiddleware as MW

    assert MW is not None
