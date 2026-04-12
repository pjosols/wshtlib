"""Tests for wshtlib.logger"""

import json
import logging
import os

import pytest

import wshtlib.logger as logger_mod
from wshtlib.context import clear_context, init_context
from wshtlib.logger import get_logger, set_lambda_context


@pytest.fixture(autouse=True)
def reset_state(monkeypatch: pytest.MonkeyPatch) -> None:
    clear_context()
    # Reset cold_start between tests
    monkeypatch.setattr(logger_mod, "_cold_start", True)
    # Remove any cached logger so each test gets a fresh one
    logger_mod.logging.Logger.manager.loggerDict.pop("test.svc", None)


def _capture_output(logger: logging.Logger) -> list[str]:
    """Return list to collect log output; attaches a capturing handler."""
    records: list[str] = []

    class Cap(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            records.append(self.format(record))

    h = Cap()
    # Reuse the formatter from the logger's first handler
    h.setFormatter(logger.handlers[0].formatter)
    logger.addHandler(h)
    return records


def test_get_logger_returns_same_instance() -> None:
    a = get_logger("test.svc")
    b = get_logger("test.svc")
    assert a is b


def test_log_output_is_json(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LOG_LEVEL", "DEBUG")
    logger_mod.logging.Logger.manager.loggerDict.pop("test.svc", None)
    lg = get_logger("test.svc")
    records = _capture_output(lg)
    lg.info("hello")
    data = json.loads(records[-1])
    assert data["message"] == "hello"
    assert data["level"] == "INFO"


def test_log_includes_extra_kwargs() -> None:
    lg = get_logger("test.svc")
    records = _capture_output(lg)
    lg.info("msg", request_id="abc")  # type: ignore[call-arg]
    data = json.loads(records[-1])
    assert data["request_id"] == "abc"


def test_log_includes_trace_id_from_context() -> None:
    ctx_obj = type("C", (), {"aws_request_id": "r"})()
    init_context({"headers": {"x-amzn-trace-id": "Root=X"}}, ctx_obj)
    lg = get_logger("test.svc")
    records = _capture_output(lg)
    lg.info("traced")
    data = json.loads(records[-1])
    assert data["trace_id"] == "Root=X"


def test_log_no_trace_id_when_context_empty() -> None:
    lg = get_logger("test.svc")
    records = _capture_output(lg)
    lg.info("no trace")
    data = json.loads(records[-1])
    assert "trace_id" not in data


def test_set_lambda_context_cold_start(monkeypatch: pytest.MonkeyPatch) -> None:
    # Test cold_start directly on the formatter to avoid other loggers consuming it
    monkeypatch.setattr(logger_mod, "_cold_start", True)
    lg = get_logger("test.svc")
    records = _capture_output(lg)
    ctx = type("C", (), {"function_name": "fn", "invoked_function_arn": "arn", "memory_limit_in_mb": 128, "aws_request_id": "r1"})()
    lg._formatter.set_lambda_context(ctx)  # call directly on formatter, not module-level
    lg.info("after lambda ctx")
    data = json.loads(records[-1])
    assert data["cold_start"] is True
    assert data["function_name"] == "fn"


def test_set_lambda_context_warm_start() -> None:
    lg = get_logger("test.svc")
    records = _capture_output(lg)
    ctx = type("C", (), {"function_name": "fn", "invoked_function_arn": "arn", "memory_limit_in_mb": 128, "aws_request_id": "r1"})()
    set_lambda_context(ctx)
    set_lambda_context(ctx)  # second call → warm
    lg.info("warm")
    data = json.loads(records[-1])
    assert data["cold_start"] is False


def test_detect_runtime_lambda(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AWS_LAMBDA_FUNCTION_NAME", "my-fn")
    result = logger_mod._detect_runtime()
    assert result == {"runtime": "lambda"}


def test_detect_runtime_ecs(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("AWS_LAMBDA_FUNCTION_NAME", raising=False)
    monkeypatch.setenv("ECS_CONTAINER_METADATA_URI_V4", "http://169.254.170.2/v4")
    result = logger_mod._detect_runtime()
    assert result == {"runtime": "ecs"}


def test_detect_runtime_local(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("AWS_LAMBDA_FUNCTION_NAME", raising=False)
    monkeypatch.delenv("ECS_CONTAINER_METADATA_URI_V4", raising=False)
    result = logger_mod._detect_runtime()
    assert result["runtime"] == "local"
    assert "hostname" in result
    assert "pid" in result


def test_log_level_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LOG_LEVEL", "WARNING")
    logger_mod.logging.Logger.manager.loggerDict.pop("test.svc", None)
    lg = get_logger("test.svc")
    assert lg.level == logging.WARNING
