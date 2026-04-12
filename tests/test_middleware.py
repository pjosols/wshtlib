"""Tests for wshtlib.middleware"""

import pytest


def test_middleware_class_available_when_starlette_installed() -> None:
    """WshtlibMiddleware is importable when starlette is present."""
    try:
        from starlette.testclient import TestClient  # noqa: F401
        starlette_available = True
    except ImportError:
        starlette_available = False

    if not starlette_available:
        pytest.skip("starlette not installed")

    from wshtlib.middleware import WshtlibMiddleware
    assert WshtlibMiddleware is not None


@pytest.mark.asyncio
async def test_middleware_sets_trace_header() -> None:
    pytest.importorskip("starlette")
    from starlette.applications import Starlette
    from starlette.requests import Request
    from starlette.responses import PlainTextResponse
    from starlette.routing import Route
    from starlette.testclient import TestClient

    from wshtlib.middleware import WshtlibMiddleware

    async def homepage(request: Request) -> PlainTextResponse:
        return PlainTextResponse("ok")

    app = Starlette(routes=[Route("/", homepage)])
    app.add_middleware(WshtlibMiddleware)

    client = TestClient(app, raise_server_exceptions=True)
    resp = client.get("/", headers={"x-amzn-trace-id": "Root=1"})
    assert resp.status_code == 200
    assert resp.headers.get("x-trace-id") == "Root=1"


@pytest.mark.asyncio
async def test_middleware_no_trace_header_when_absent() -> None:
    pytest.importorskip("starlette")
    from starlette.applications import Starlette
    from starlette.requests import Request
    from starlette.responses import PlainTextResponse
    from starlette.routing import Route
    from starlette.testclient import TestClient

    from wshtlib.middleware import WshtlibMiddleware

    async def homepage(request: Request) -> PlainTextResponse:
        return PlainTextResponse("ok")

    app = Starlette(routes=[Route("/", homepage)])
    app.add_middleware(WshtlibMiddleware)

    client = TestClient(app)
    resp = client.get("/")
    assert "x-trace-id" not in resp.headers
