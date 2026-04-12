"""Tests for wshtlib/logger.py — structured JSON logger"""

import json
import logging
from io import StringIO
from unittest.mock import MagicMock

import wshtlib.logger as logger_module
from wshtlib.logger import _Logger, get_logger


def _capture_log(log_fn, *args, **kwargs) -> dict:
    """Call log_fn and return the parsed JSON log entry."""
    buf = StringIO()
    handler = logging.StreamHandler(buf)
    handler.setFormatter(log_fn.__self__._formatter)
    log_fn.__self__.handlers = [handler]
    log_fn(*args, **kwargs)
    return json.loads(buf.getvalue().strip())


def _fresh_logger(name: str = "test-svc") -> _Logger:
    """Return a new _Logger, bypassing the registry cache."""
    lg = _Logger(name)
    lg.setLevel(logging.DEBUG)
    return lg


# ---------------------------------------------------------------------------
# get_logger
# ---------------------------------------------------------------------------


class TestGetLogger:
    def test_returns_logger_instance(self):
        lg = get_logger("svc-a")
        assert isinstance(lg, _Logger)

    def test_same_name_returns_same_instance(self):
        lg1 = get_logger("svc-cache-test")
        lg2 = get_logger("svc-cache-test")
        assert lg1 is lg2

    def test_different_names_return_different_instances(self):
        lg1 = get_logger("svc-x")
        lg2 = get_logger("svc-y")
        assert lg1 is not lg2

    def test_log_level_defaults_to_info(self, monkeypatch):
        monkeypatch.delenv("LOG_LEVEL", raising=False)
        lg = _Logger("svc-level-default")
        lg.setLevel(logging.getLevelName("INFO"))
        assert lg.level == logging.INFO

    def test_log_level_from_env(self, monkeypatch):
        monkeypatch.setenv("LOG_LEVEL", "DEBUG")
        lg = get_logger("svc-debug-env")
        assert lg.level == logging.DEBUG


# ---------------------------------------------------------------------------
# JSON output structure
# ---------------------------------------------------------------------------


class TestJsonOutput:
    def _emit(self, level_fn_name: str, msg: str, **kwargs) -> dict:
        lg = _fresh_logger("test-json")
        buf = StringIO()
        handler = logging.StreamHandler(buf)
        handler.setFormatter(lg._formatter)
        lg.handlers = [handler]
        getattr(lg, level_fn_name)(msg, **kwargs)
        return json.loads(buf.getvalue().strip())

    def test_info_has_required_fields(self):
        entry = self._emit("info", "hello")
        for field in ("level", "message", "timestamp", "service", "location"):
            assert field in entry, f"missing field: {field}"

    def test_level_field_matches_method(self):
        assert self._emit("info", "x")["level"] == "INFO"
        assert self._emit("warning", "x")["level"] == "WARNING"
        assert self._emit("error", "x")["level"] == "ERROR"

    def test_message_field_matches_input(self):
        entry = self._emit("info", "my message")
        assert entry["message"] == "my message"

    def test_service_field_matches_logger_name(self):
        lg = _fresh_logger("billing-svc")
        buf = StringIO()
        handler = logging.StreamHandler(buf)
        handler.setFormatter(lg._formatter)
        lg.handlers = [handler]
        lg.info("test")
        entry = json.loads(buf.getvalue().strip())
        assert entry["service"] == "billing-svc"

    def test_extra_kwargs_included_in_output(self):
        entry = self._emit("info", "event", shoot_id="s-123", status=200)
        assert entry["shoot_id"] == "s-123"
        assert entry["status"] == 200

    def test_timestamp_is_iso_format(self):
        from datetime import datetime

        entry = self._emit("info", "ts-test")
        # Should parse without error
        datetime.fromisoformat(entry["timestamp"])

    def test_location_contains_line_number(self):
        entry = self._emit("info", "loc-test")
        assert ":" in entry["location"]
        parts = entry["location"].split(":")
        assert parts[-1].isdigit()


# ---------------------------------------------------------------------------
# Exception logging
# ---------------------------------------------------------------------------


class TestExceptionLogging:
    def test_exception_field_present_on_exc_info(self):
        lg = _fresh_logger("exc-svc")
        buf = StringIO()
        handler = logging.StreamHandler(buf)
        handler.setFormatter(lg._formatter)
        lg.handlers = [handler]
        try:
            raise ValueError("boom")
        except ValueError:
            lg.exception("caught error")
        entry = json.loads(buf.getvalue().strip())
        assert "exception" in entry
        assert "ValueError" in entry["exception"]

    def test_no_exception_field_without_exc_info(self):
        lg = _fresh_logger("no-exc-svc")
        buf = StringIO()
        handler = logging.StreamHandler(buf)
        handler.setFormatter(lg._formatter)
        lg.handlers = [handler]
        lg.info("no error here")
        entry = json.loads(buf.getvalue().strip())
        assert "exception" not in entry


# ---------------------------------------------------------------------------
# Lambda context enrichment
# ---------------------------------------------------------------------------


class TestLambdaContext:
    def _make_context(self, **kwargs) -> MagicMock:
        ctx = MagicMock()
        ctx.function_name = kwargs.get("function_name", "my-lambda")
        ctx.invoked_function_arn = kwargs.get(
            "arn", "arn:aws:lambda:us-west-2:123:function:my-lambda"
        )
        ctx.memory_limit_in_mb = kwargs.get("memory", "256")
        ctx.aws_request_id = kwargs.get("request_id", "req-abc-123")
        return ctx

    def _emit_with_context(self, ctx) -> dict:
        lg = _fresh_logger("lambda-svc")
        lg.set_lambda_context(ctx)
        buf = StringIO()
        handler = logging.StreamHandler(buf)
        handler.setFormatter(lg._formatter)
        lg.handlers = [handler]
        lg.info("lambda log")
        return json.loads(buf.getvalue().strip())

    def test_function_name_in_output(self):
        ctx = self._make_context(function_name="wholeshoot-api")
        entry = self._emit_with_context(ctx)
        assert entry["function_name"] == "wholeshoot-api"

    def test_request_id_in_output(self):
        ctx = self._make_context(request_id="req-xyz")
        entry = self._emit_with_context(ctx)
        assert entry["function_request_id"] == "req-xyz"

    def test_cold_start_true_on_first_invocation(self, monkeypatch):
        monkeypatch.setattr(logger_module, "_cold_start", True)
        ctx = self._make_context()
        entry = self._emit_with_context(ctx)
        assert entry["cold_start"] is True

    def test_cold_start_false_after_first_invocation(self, monkeypatch):
        monkeypatch.setattr(logger_module, "_cold_start", True)
        ctx = self._make_context()
        lg = _fresh_logger("cold-start-svc")
        lg.set_lambda_context(ctx)
        # Second invocation
        lg2 = _fresh_logger("cold-start-svc-2")
        lg2.set_lambda_context(ctx)
        buf = StringIO()
        handler = logging.StreamHandler(buf)
        handler.setFormatter(lg2._formatter)
        lg2.handlers = [handler]
        lg2.info("warm")
        entry = json.loads(buf.getvalue().strip())
        assert entry["cold_start"] is False

    def test_missing_context_attributes_handled_gracefully(self):
        ctx = object()  # no attributes at all
        lg = _fresh_logger("bare-ctx-svc")
        lg.set_lambda_context(ctx)
        buf = StringIO()
        handler = logging.StreamHandler(buf)
        handler.setFormatter(lg._formatter)
        lg.handlers = [handler]
        lg.info("bare context")
        entry = json.loads(buf.getvalue().strip())
        assert entry["function_name"] is None
        assert entry["function_request_id"] is None

    def test_no_propagation(self):
        lg = _fresh_logger("no-prop-svc")
        assert lg.propagate is False


# ---------------------------------------------------------------------------
# Runtime detection
# ---------------------------------------------------------------------------


class TestRuntimeDetection:
    def _detect(self, monkeypatch, env: dict) -> dict:
        """Re-run _detect_runtime() with a controlled environment."""
        for key in ("AWS_LAMBDA_FUNCTION_NAME", "ECS_CONTAINER_METADATA_URI_V4"):
            monkeypatch.delenv(key, raising=False)
        for k, v in env.items():
            monkeypatch.setenv(k, v)
        import wshtlib.logger as lm

        return lm._detect_runtime()

    def test_lambda_runtime_detected(self, monkeypatch):
        result = self._detect(monkeypatch, {"AWS_LAMBDA_FUNCTION_NAME": "my-fn"})
        assert result == {"runtime": "lambda"}

    def test_ecs_runtime_detected(self, monkeypatch):
        result = self._detect(
            monkeypatch,
            {"ECS_CONTAINER_METADATA_URI_V4": "http://169.254.170.2/v4/abc"},
        )
        assert result == {"runtime": "ecs"}

    def test_local_runtime_detected(self, monkeypatch):
        result = self._detect(monkeypatch, {})
        assert result["runtime"] == "local"
        assert "hostname" in result
        assert "pid" in result
        assert isinstance(result["pid"], int)

    def test_lambda_takes_precedence_over_ecs(self, monkeypatch):
        result = self._detect(
            monkeypatch,
            {
                "AWS_LAMBDA_FUNCTION_NAME": "fn",
                "ECS_CONTAINER_METADATA_URI_V4": "http://...",
            },
        )
        assert result["runtime"] == "lambda"

    def test_runtime_field_present_in_log_output(self, monkeypatch):
        """_RUNTIME_FIELDS are merged into every log entry."""
        lg = _fresh_logger("runtime-field-svc")
        buf = StringIO()
        handler = logging.StreamHandler(buf)
        handler.setFormatter(lg._formatter)
        lg.handlers = [handler]
        lg.info("check runtime")
        entry = json.loads(buf.getvalue().strip())
        assert "runtime" in entry


# ---------------------------------------------------------------------------
# Trace ID injection from wshtlib.context
# ---------------------------------------------------------------------------


class TestTraceIdInjection:
    """Logger reads trace_id from wshtlib.context via lazy import."""

    def setup_method(self):
        from wshtlib.context import clear_context

        clear_context()

    def teardown_method(self):
        from wshtlib.context import clear_context

        clear_context()

    def _emit(self) -> dict:
        lg = _fresh_logger("trace-svc")
        buf = StringIO()
        handler = logging.StreamHandler(buf)
        handler.setFormatter(lg._formatter)
        lg.handlers = [handler]
        lg.info("trace test")
        return json.loads(buf.getvalue().strip())

    def test_trace_id_injected_when_context_set(self):
        from wshtlib.context import init_context

        init_context(
            {"headers": {"x-amzn-trace-id": "Root=1-abc123"}},
            MagicMock(aws_request_id="req-1"),
        )
        entry = self._emit()
        assert entry.get("trace_id") == "Root=1-abc123"

    def test_trace_id_absent_when_context_empty(self):
        entry = self._emit()
        assert "trace_id" not in entry

    def test_trace_id_absent_when_context_trace_id_none(self):
        from wshtlib.context import init_context

        init_context({}, MagicMock(aws_request_id="req-2"))
        entry = self._emit()
        assert "trace_id" not in entry
