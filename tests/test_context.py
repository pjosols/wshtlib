"""Tests for wshtlib/context.py — request-scoped context store"""

from unittest.mock import MagicMock

from wshtlib.context import (
    clear_context,
    get_context,
    init_context,
    init_context_from_request,
    set_user_id,
)


def setup_function():
    clear_context()


# --- init_context ---


def test_init_context_trace_id_from_header():
    event = {"headers": {"x-amzn-trace-id": "Root=1-abc"}}
    lctx = MagicMock(aws_request_id="req-123")
    init_context(event, lctx)
    c = get_context()
    assert c["trace_id"] == "Root=1-abc"
    assert c["correlation_id"] == "req-123"
    assert c["user_id"] is None


def test_init_context_trace_id_from_request_context():
    event = {"requestContext": {"requestId": "apigw-req-id"}}
    lctx = MagicMock(aws_request_id="req-456")
    init_context(event, lctx)
    c = get_context()
    assert c["trace_id"] == "apigw-req-id"


def test_init_context_header_takes_precedence_over_request_context():
    event = {
        "headers": {"x-amzn-trace-id": "Root=1-header"},
        "requestContext": {"requestId": "apigw-id"},
    }
    lctx = MagicMock(aws_request_id="req-789")
    init_context(event, lctx)
    assert get_context()["trace_id"] == "Root=1-header"


def test_init_context_no_trace_id():
    init_context({}, MagicMock(aws_request_id="req-000"))
    assert get_context()["trace_id"] is None


def test_init_context_null_headers():
    event = {"headers": None}
    init_context(event, MagicMock(aws_request_id="req-null"))
    assert get_context()["trace_id"] is None


def test_init_context_no_aws_request_id():
    lctx = object()  # no aws_request_id attribute
    init_context({}, lctx)
    assert get_context()["correlation_id"] is None


# --- init_context_from_request ---


def _make_request(headers: dict, path: str = "/test") -> MagicMock:
    req = MagicMock()
    req.headers = headers
    req.scope = {"path": path}
    return req


def test_init_context_from_request_trace_id():
    req = _make_request({"x-amzn-trace-id": "Root=1-req", "x-correlation-id": "corr-1"})
    init_context_from_request(req)
    c = get_context()
    assert c["trace_id"] == "Root=1-req"
    assert c["correlation_id"] == "corr-1"
    assert c["user_id"] is None


def test_init_context_from_request_correlation_id_fallback_to_path():
    req = _make_request({"x-amzn-trace-id": "Root=1-x"}, path="/shoots/abc")
    init_context_from_request(req)
    assert get_context()["correlation_id"] == "/shoots/abc"


def test_init_context_from_request_no_trace_id():
    req = _make_request({})
    init_context_from_request(req)
    assert get_context()["trace_id"] is None


# --- get_context returns a copy ---


def test_get_context_returns_copy():
    init_context({}, MagicMock(aws_request_id="r"))
    c1 = get_context()
    c1["injected"] = True
    assert "injected" not in get_context()


# --- set_user_id ---


def test_set_user_id():
    init_context({}, MagicMock(aws_request_id="r"))
    set_user_id("user-sub-abc")
    assert get_context()["user_id"] == "user-sub-abc"


def test_set_user_id_none():
    init_context({}, MagicMock(aws_request_id="r"))
    set_user_id("user-sub-abc")
    set_user_id(None)
    assert get_context()["user_id"] is None


def test_set_user_id_preserves_other_fields():
    init_context(
        {"headers": {"x-amzn-trace-id": "Root=1-keep"}},
        MagicMock(aws_request_id="r"),
    )
    set_user_id("u")
    c = get_context()
    assert c["trace_id"] == "Root=1-keep"
    assert c["user_id"] == "u"


# --- clear_context ---


def test_clear_context():
    init_context({}, MagicMock(aws_request_id="r"))
    clear_context()
    assert get_context() == {}


# --- context isolation between coroutines ---


def test_context_isolation_between_tasks():
    """Each asyncio task gets its own context copy via contextvars."""
    import asyncio

    async def task_a():
        init_context(
            {"headers": {"x-amzn-trace-id": "A"}}, MagicMock(aws_request_id="a")
        )
        await asyncio.sleep(0)
        return get_context()["trace_id"]

    async def task_b():
        init_context(
            {"headers": {"x-amzn-trace-id": "B"}}, MagicMock(aws_request_id="b")
        )
        await asyncio.sleep(0)
        return get_context()["trace_id"]

    async def run():
        results = await asyncio.gather(task_a(), task_b())
        return results

    a, b = asyncio.run(run())
    assert a == "A"
    assert b == "B"
