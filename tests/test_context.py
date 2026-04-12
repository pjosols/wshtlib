"""Tests for wshtlib.context"""

import pytest

from wshtlib.context import (
    clear_context,
    get_context,
    init_context,
    init_context_from_request,
    set_user_id,
)


@pytest.fixture(autouse=True)
def reset() -> None:
    clear_context()


# --- init_context ---


def test_init_context_trace_from_header() -> None:
    event = {"headers": {"x-amzn-trace-id": "Root=1"}}
    ctx_obj = type("C", (), {"aws_request_id": "req-1"})()
    init_context(event, ctx_obj)
    assert get_context()["trace_id"] == "Root=1"


def test_init_context_trace_from_request_context() -> None:
    event = {"requestContext": {"requestId": "req-abc"}}
    ctx_obj = type("C", (), {"aws_request_id": "req-abc"})()
    init_context(event, ctx_obj)
    assert get_context()["trace_id"] == "req-abc"


def test_init_context_correlation_id() -> None:
    ctx_obj = type("C", (), {"aws_request_id": "req-2"})()
    init_context({}, ctx_obj)
    assert get_context()["correlation_id"] == "req-2"


def test_init_context_user_id_none() -> None:
    ctx_obj = type("C", (), {"aws_request_id": "r"})()
    init_context({}, ctx_obj)
    assert get_context()["user_id"] is None


def test_init_context_null_headers() -> None:
    event = {"headers": None}
    ctx_obj = type("C", (), {"aws_request_id": "r"})()
    init_context(event, ctx_obj)
    assert get_context()["trace_id"] is None


# --- init_context_from_request ---


def _make_request(headers: dict, path: str = "/test") -> object:
    req = type(
        "R",
        (),
        {
            "headers": headers,
            "scope": {"path": path},
        },
    )()
    return req


def test_init_context_from_request_trace_id() -> None:
    req = _make_request({"x-amzn-trace-id": "Root=2"})
    init_context_from_request(req)
    assert get_context()["trace_id"] == "Root=2"


def test_init_context_from_request_correlation_from_header() -> None:
    req = _make_request({"x-correlation-id": "corr-1"})
    init_context_from_request(req)
    assert get_context()["correlation_id"] == "corr-1"


def test_init_context_from_request_correlation_fallback_path() -> None:
    req = _make_request({}, path="/api/v1")
    init_context_from_request(req)
    assert get_context()["correlation_id"] == "/api/v1"


# --- get_context / set_user_id / clear_context ---


def test_get_context_returns_copy() -> None:
    ctx_obj = type("C", (), {"aws_request_id": "r"})()
    init_context({}, ctx_obj)
    c1 = get_context()
    c1["injected"] = True
    assert "injected" not in get_context()


def test_set_user_id() -> None:
    ctx_obj = type("C", (), {"aws_request_id": "r"})()
    init_context({}, ctx_obj)
    set_user_id("user-42")
    assert get_context()["user_id"] == "user-42"


def test_clear_context() -> None:
    ctx_obj = type("C", (), {"aws_request_id": "r"})()
    init_context({}, ctx_obj)
    clear_context()
    assert get_context() == {}
