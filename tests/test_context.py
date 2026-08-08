"""Test request-scoped context store."""

import uuid
from unittest.mock import MagicMock

from wshtlib.context import (
    clear_context,
    get_context,
    init_context,
    init_context_from_request,
    resolve_service,
    set_service,
    set_user_id,
)


def setup_function() -> None:
    clear_context()


# --- init_context ---


def test_init_context_trace_id_from_header() -> None:
    event = {"headers": {"x-amzn-trace-id": "Root=1-abc"}}
    lctx = MagicMock(aws_request_id="req-123")
    init_context(event, lctx)
    c = get_context()
    assert c["trace_id"] == "Root=1-abc"
    assert c["correlation_id"] == "req-123"
    assert c["user_id"] is None


def test_init_context_trace_id_from_request_context() -> None:
    event = {"requestContext": {"requestId": "apigw-req-id"}}
    lctx = MagicMock(aws_request_id="req-456")
    init_context(event, lctx)
    c = get_context()
    assert c["trace_id"] == "apigw-req-id"


def test_init_context_header_takes_precedence_over_request_context() -> None:
    event = {
        "headers": {"x-amzn-trace-id": "Root=1-header"},
        "requestContext": {"requestId": "apigw-id"},
    }
    lctx = MagicMock(aws_request_id="req-789")
    init_context(event, lctx)
    assert get_context()["trace_id"] == "Root=1-header"


def test_init_context_no_trace_id() -> None:
    init_context({}, MagicMock(aws_request_id="req-000"))
    assert get_context()["trace_id"] is None


def test_init_context_null_headers() -> None:
    event = {"headers": None}
    init_context(event, MagicMock(aws_request_id="req-null"))
    assert get_context()["trace_id"] is None


def test_init_context_no_aws_request_id() -> None:
    lctx = object()  # no aws_request_id attribute
    init_context({}, lctx)
    assert get_context()["correlation_id"] is None


# --- init_context_from_request ---


def _make_request(headers: dict, path: str = "/test") -> MagicMock:
    req = MagicMock()
    req.headers = headers
    req.scope = {"path": path}
    return req


def test_init_context_from_request_trace_id() -> None:
    req = _make_request({"x-amzn-trace-id": "Root=1-req", "x-correlation-id": "corr-1"})
    init_context_from_request(req)
    c = get_context()
    assert c["trace_id"] == "Root=1-req"
    assert c["correlation_id"] == "corr-1"
    assert c["user_id"] is None


def test_init_context_from_request_correlation_id_is_generated_per_request() -> None:
    """Two requests to one path get distinct ids.

    The fallback used to be the request path, so every call to /health shared
    the correlation id "/health" -- filtering a log search by it returned an
    unbounded mix of unrelated requests, which is the opposite of the job.
    """
    req = _make_request({"x-amzn-trace-id": "Root=1-x"}, path="/shoots/abc")
    init_context_from_request(req)
    first = get_context()["correlation_id"]
    init_context_from_request(req)
    second = get_context()["correlation_id"]

    assert first != second
    assert "/shoots/abc" not in (first, second)
    assert uuid.UUID(first).version == 4


def test_init_context_from_request_no_trace_id() -> None:
    req = _make_request({})
    init_context_from_request(req)
    assert get_context()["trace_id"] is None


# --- trace id sources ---


def test_init_context_finds_trace_header_whatever_its_casing() -> None:
    """REST APIs and ALBs keep the client's casing; only HTTP API v2 lowercases."""
    init_context(
        {
            "headers": {"X-Amzn-Trace-Id": "Root=1-rest"},
            "requestContext": {"requestId": "r-1"},
        },
        MagicMock(aws_request_id="req-1"),
    )
    assert get_context()["trace_id"] == "Root=1-rest"


def test_init_context_falls_back_to_the_lambda_trace_env_var(monkeypatch) -> None:
    """Lambda exports the active X-Ray header even where an event has no headers."""
    monkeypatch.setenv("_X_AMZN_TRACE_ID", "Root=1-env")
    init_context({}, MagicMock(aws_request_id="req-1"))
    assert get_context()["trace_id"] == "Root=1-env"


def test_request_id_is_used_only_when_no_trace_header_exists(monkeypatch) -> None:
    monkeypatch.delenv("_X_AMZN_TRACE_ID", raising=False)
    event = {
        "headers": {"content-type": "application/json"},
        "requestContext": {"requestId": "r-2"},
    }
    init_context(event, MagicMock())
    assert get_context()["trace_id"] == "r-2"


# --- service survives a new request context ---


def test_set_service_survives_init_context() -> None:
    """A module-scope set_service must outlive the per-invocation context reset.

    init_context installed a fresh three-key dict, so under @bootstrap and
    @worker -- which call it on every invocation -- set_service was silently
    dead and both logs and the metrics dimension fell back to the function name.
    """
    set_service("billing")
    init_context({}, MagicMock(aws_request_id="req-1"))
    assert resolve_service() == "billing"


def test_set_service_survives_init_context_from_request() -> None:
    set_service("billing")
    init_context_from_request(_make_request({}))
    assert resolve_service() == "billing"


def test_clear_context_clears_the_service() -> None:
    set_service("billing")
    clear_context()
    assert resolve_service() is None


# --- get_context returns a copy ---


def test_get_context_returns_copy() -> None:
    init_context({}, MagicMock(aws_request_id="r"))
    c1 = get_context()
    c1["injected"] = True
    assert "injected" not in get_context()


# --- set_user_id ---


def test_set_user_id() -> None:
    init_context({}, MagicMock(aws_request_id="r"))
    set_user_id("user-sub-abc")
    assert get_context()["user_id"] == "user-sub-abc"


def test_set_user_id_none() -> None:
    init_context({}, MagicMock(aws_request_id="r"))
    set_user_id("user-sub-abc")
    set_user_id(None)
    assert get_context()["user_id"] is None


def test_set_user_id_preserves_other_fields() -> None:
    init_context(
        {"headers": {"x-amzn-trace-id": "Root=1-keep"}},
        MagicMock(aws_request_id="r"),
    )
    set_user_id("u")
    c = get_context()
    assert c["trace_id"] == "Root=1-keep"
    assert c["user_id"] == "u"


# --- clear_context ---


def test_clear_context() -> None:
    init_context({}, MagicMock(aws_request_id="r"))
    clear_context()
    assert get_context() == {}


# --- context isolation between coroutines ---


def test_context_isolation_between_tasks() -> None:
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
