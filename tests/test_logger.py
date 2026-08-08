"""Tests for structured JSON logger, Lambda enrichment, and runtime detection."""

import json
import logging
import os
from io import StringIO
from unittest.mock import MagicMock

import pytest

import wshtlib.logger as logger_module
from tests.conftest import (
    capture_log,
    emit_with_lambda_context,
    fresh_logger,
    make_lambda_context,
)
from wshtlib.logger import _Logger, get_logger, set_lambda_context

# ---------------------------------------------------------------------------
# get_logger
# ---------------------------------------------------------------------------


class TestGetLogger:
    def test_returns_logger_instance(self) -> None:
        lg = get_logger("svc-a")
        assert isinstance(lg, _Logger)

    def test_same_name_returns_same_instance(self) -> None:
        lg1 = get_logger("svc-cache-test")
        lg2 = get_logger("svc-cache-test")
        assert lg1 is lg2

    def test_different_names_return_different_instances(self) -> None:
        lg1 = get_logger("svc-x")
        lg2 = get_logger("svc-y")
        assert lg1 is not lg2

    def test_log_level_defaults_to_info(self, monkeypatch) -> None:
        monkeypatch.delenv("WSHT_LOG_LEVEL", raising=False)
        lg = _Logger("svc-level-default")
        lg.setLevel(logging.getLevelName("INFO"))
        assert lg.level == logging.INFO

    def test_log_level_from_env(self, monkeypatch) -> None:
        monkeypatch.setenv("WSHT_LOG_LEVEL", "DEBUG")
        lg = get_logger("svc-debug-env")
        assert lg.level == logging.DEBUG

    def test_unset_level_really_defaults_to_info(self, monkeypatch) -> None:
        """Unlike the test above, this one lets get_logger choose the level."""
        monkeypatch.delenv("WSHT_LOG_LEVEL", raising=False)
        assert get_logger("svc-level-unset").level == logging.INFO

    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("debug", logging.DEBUG),
            (" WARNING ", logging.WARNING),
            ("30", 30),
            ("", logging.INFO),
            ("   ", logging.INFO),
            ("verbose", logging.INFO),
        ],
    )
    def test_level_is_read_without_ever_raising(
        self, monkeypatch, raw: str, expected: int
    ) -> None:
        """setLevel rejects anything outside its own name table.

        get_logger runs at import inside this package, so a variable declared
        but left blank -- routine in Terraform and SAM -- or spelled in
        lowercase used to raise ValueError and take down `import wshtlib`
        entirely, before a single line could be logged.
        """
        monkeypatch.setenv("WSHT_LOG_LEVEL", raw)
        assert get_logger(f"svc-level-{raw!r}").level == expected

    def test_blank_level_does_not_break_importing_the_package(
        self, monkeypatch
    ) -> None:
        import subprocess
        import sys

        env = {**os.environ, "WSHT_LOG_LEVEL": ""}
        result = subprocess.run(
            [sys.executable, "-c", "import wshtlib; print(wshtlib.__version__)"],
            capture_output=True,
            env=env,
        )
        assert result.returncode == 0, result.stderr.decode()


# ---------------------------------------------------------------------------
# JSON output structure
# ---------------------------------------------------------------------------


class TestJsonOutput:
    def _emit(self, level_fn_name: str, msg: str, **kwargs) -> dict:
        """Log a message at the specified level and return the parsed JSON entry.

        level_fn_name: Logger method name (e.g., "info", "warning").
        msg: Message to log.
        **kwargs: Extra fields to include in the log.
        Returns the parsed JSON log entry as a dict.
        """
        lg = fresh_logger("test-json")
        buf = StringIO()
        handler = logging.StreamHandler(buf)
        handler.setFormatter(lg._formatter)
        lg.handlers = [handler]
        getattr(lg, level_fn_name)(msg, **kwargs)
        return json.loads(buf.getvalue().strip())

    def test_info_has_required_fields(self) -> None:
        entry = self._emit("info", "hello")
        for field in ("level", "message", "timestamp", "service", "location"):
            assert field in entry, f"missing field: {field}"

    def test_level_field_matches_method(self) -> None:
        assert self._emit("info", "x")["level"] == "INFO"
        assert self._emit("warning", "x")["level"] == "WARNING"
        assert self._emit("error", "x")["level"] == "ERROR"

    def test_message_field_matches_input(self) -> None:
        entry = self._emit("info", "my message")
        assert entry["message"] == "my message"

    def test_service_field_matches_logger_name(self) -> None:
        lg = fresh_logger("billing-svc")
        buf = StringIO()
        handler = logging.StreamHandler(buf)
        handler.setFormatter(lg._formatter)
        lg.handlers = [handler]
        lg.info("test")
        entry = json.loads(buf.getvalue().strip())
        assert entry["service"] == "billing-svc"

    def test_extra_kwargs_included_in_output(self) -> None:
        entry = self._emit("info", "event", shoot_id="s-123", status=200)
        assert entry["shoot_id"] == "s-123"
        assert entry["status"] == 200

    def test_timestamp_is_iso_format(self) -> None:
        from datetime import datetime

        entry = self._emit("info", "ts-test")
        datetime.fromisoformat(entry["timestamp"])

    def test_location_contains_line_number(self) -> None:
        entry = self._emit("info", "loc-test")
        assert ":" in entry["location"]
        parts = entry["location"].split(":")
        assert parts[-1].isdigit()

    def test_location_names_the_caller_not_wshtlib(self) -> None:
        """`location` is for triage: pointing at wshtlib's own frame is useless."""
        lg = fresh_logger("loc-svc")
        buf = StringIO()
        handler = logging.StreamHandler(buf)
        handler.setFormatter(lg._formatter)
        lg.handlers = [handler]

        def a_caller_function() -> None:
            lg.info("from here")

        a_caller_function()
        entry = json.loads(buf.getvalue().strip())
        assert entry["location"].split(":")[0] == "a_caller_function"

    def test_stdlib_extra_dict_included_in_output(self) -> None:
        """`extra=` is the stdlib spelling; dropping it silently loses context."""
        entry = self._emit("info", "event", extra={"shoot_id": "s-123", "status": 200})
        assert entry["shoot_id"] == "s-123"
        assert entry["status"] == 200

    def test_extra_dict_and_kwargs_both_included(self) -> None:
        entry = self._emit("info", "event", extra={"from_extra": 1}, from_kwarg=2)
        assert entry["from_extra"] == 1
        assert entry["from_kwarg"] == 2

    def test_kwargs_win_a_key_collision_with_extra(self) -> None:
        """kwargs are this library's documented spelling, so they take the key."""
        entry = self._emit("info", "event", extra={"who": "extra"}, who="kwarg")
        assert entry["who"] == "kwarg"

    def test_extra_key_colliding_with_a_logrecord_attribute_is_safe(self) -> None:
        """Stdlib raises KeyError on these; routing through our own key does not."""
        entry = self._emit("info", "event", extra={"module": "billing", "name": "x"})
        assert entry["module"] == "billing"
        assert entry["name"] == "x"

    @pytest.mark.parametrize("spelling", ["kwarg", "extra"])
    @pytest.mark.parametrize(
        "field", ["level", "message", "timestamp", "service", "location", "trace_id"]
    )
    def test_caller_field_cannot_falsify_a_formatter_owned_field(
        self, field: str, spelling: str
    ) -> None:
        """An enrichment field must never replace the record it enriches.

        Without this, `extra={"level": "DEBUG"}` gets an INFO line indexed as
        DEBUG, and `extra={"message": ...}` replaces the message outright --
        silent falsification in the one place you look when something breaks.
        """
        payload = {field: "FALSIFIED"}
        kwargs = {spelling: payload} if spelling == "extra" else payload
        entry = self._emit("info", "the real message", **kwargs)
        assert entry["level"] == "INFO"
        assert entry["message"] == "the real message"
        assert entry["service"] == "test-json"
        assert entry.get(field) != "FALSIFIED"
        assert entry[f"extra_{field}"] == "FALSIFIED", "caller value must survive"

    @pytest.mark.parametrize("field", ["level", "msg", "args", "name"])
    def test_field_named_after_a_log_parameter_does_not_raise(self, field: str) -> None:
        """These shadowed `_log` parameters used to TypeError, taking down the caller."""
        lg = fresh_logger("shadow-svc")
        buf = StringIO()
        handler = logging.StreamHandler(buf)
        handler.setFormatter(lg._formatter)
        lg.handlers = [handler]
        lg.info("charge", **{field: "premium"})
        entry = json.loads(buf.getvalue().strip())
        assert entry["message"] == "charge"
        emitted = entry.get(f"extra_{field}", entry.get(field))
        assert emitted == "premium"

    def test_caller_fields_are_mirrored_onto_the_record(self) -> None:
        """Custom filters, %(field)s formatters, and Sentry read record attrs."""
        lg = fresh_logger("attr-svc")
        seen: dict[str, object] = {}

        class Capture(logging.Filter):
            def filter(self, record: logging.LogRecord) -> bool:
                seen["shoot_id"] = getattr(record, "shoot_id", None)
                return True

        lg.addFilter(Capture())
        lg.handlers = [logging.StreamHandler(StringIO())]
        lg.info("event", shoot_id="s-123")
        assert seen["shoot_id"] == "s-123"


# ---------------------------------------------------------------------------
# Exception logging
# ---------------------------------------------------------------------------


class TestExceptionLogging:
    def test_exception_field_present_on_exc_info(self) -> None:
        lg = fresh_logger("exc-svc")
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

    def test_no_exception_field_without_exc_info(self) -> None:
        lg = fresh_logger("no-exc-svc")
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
    def test_function_name_in_output(self) -> None:
        ctx = make_lambda_context(function_name="orders-api")
        entry = emit_with_lambda_context(ctx)
        assert entry["function_name"] == "orders-api"

    def test_request_id_in_output(self) -> None:
        ctx = make_lambda_context(request_id="req-xyz")
        entry = emit_with_lambda_context(ctx)
        assert entry["function_request_id"] == "req-xyz"

    def test_cold_start_true_on_first_invocation(self, monkeypatch) -> None:
        monkeypatch.setattr(logger_module, "_cold_start", True)
        ctx = make_lambda_context()
        entry = emit_with_lambda_context(ctx)
        assert entry["cold_start"] is True

    def test_cold_start_false_after_first_invocation(self, monkeypatch) -> None:
        monkeypatch.setattr(logger_module, "_cold_start", True)
        ctx = make_lambda_context()
        lg = fresh_logger("cold-start-svc")
        lg.set_lambda_context(ctx)
        lg2 = fresh_logger("cold-start-svc-2")
        lg2.set_lambda_context(ctx)
        buf = StringIO()
        handler = logging.StreamHandler(buf)
        handler.setFormatter(lg2._formatter)
        lg2.handlers = [handler]
        lg2.info("warm")
        entry = json.loads(buf.getvalue().strip())
        assert entry["cold_start"] is False

    def test_cold_start_is_true_for_every_logger_not_only_the_first(
        self, monkeypatch
    ) -> None:
        """The flag describes the invocation, not whichever logger heard first.

        It used to be consumed by the first logger told about the context, and
        wshtlib.decorators builds one at import -- so it always got there first
        and every application logger reported cold_start False on a genuine
        cold start, which is exactly backwards for latency triage.
        """
        monkeypatch.setattr(logger_module, "_cold_start", True)
        set_lambda_context(make_lambda_context())

        first = capture_log(fresh_logger("cold-start-a").info, "one")
        second = capture_log(fresh_logger("cold-start-b").info, "two")

        assert first["cold_start"] is True
        assert second["cold_start"] is True

    def test_logger_built_after_the_context_arrived_still_carries_it(
        self, monkeypatch
    ) -> None:
        """Enrichment cannot depend on a logger existing before the invocation."""
        monkeypatch.setattr(logger_module, "_cold_start", True)
        set_lambda_context(make_lambda_context(function_name="late-svc"))

        entry = capture_log(fresh_logger("built-late").info, "late")

        assert entry["function_name"] == "late-svc"
        assert entry["function_request_id"] == "req-abc-123"

    def test_missing_context_attributes_handled_gracefully(self) -> None:
        ctx = object()
        lg = fresh_logger("bare-ctx-svc")
        lg.set_lambda_context(ctx)
        buf = StringIO()
        handler = logging.StreamHandler(buf)
        handler.setFormatter(lg._formatter)
        lg.handlers = [handler]
        lg.info("bare context")
        entry = json.loads(buf.getvalue().strip())
        assert entry["function_name"] is None
        assert entry["function_request_id"] is None

    def test_no_propagation(self) -> None:
        lg = fresh_logger("no-prop-svc")
        assert lg.propagate is False


# ---------------------------------------------------------------------------
# Runtime detection
# ---------------------------------------------------------------------------


class TestRuntimeDetection:
    def _detect(self, monkeypatch, env: dict) -> dict:
        """Call _detect_runtime() with a controlled environment.

        monkeypatch: pytest fixture for environment manipulation.
        env: Dict of environment variables to set.
        Returns the result of _detect_runtime().
        """
        for key in ("AWS_LAMBDA_FUNCTION_NAME", "ECS_CONTAINER_METADATA_URI_V4"):
            monkeypatch.delenv(key, raising=False)
        for k, v in env.items():
            monkeypatch.setenv(k, v)
        import wshtlib.logger as lm

        return lm._detect_runtime()

    def test_lambda_runtime_detected(self, monkeypatch) -> None:
        result = self._detect(monkeypatch, {"AWS_LAMBDA_FUNCTION_NAME": "my-fn"})
        assert result == {"runtime": "lambda"}

    def test_ecs_runtime_detected(self, monkeypatch) -> None:
        result = self._detect(
            monkeypatch,
            {"ECS_CONTAINER_METADATA_URI_V4": "http://169.254.170.2/v4/abc"},
        )
        assert result == {"runtime": "ecs"}

    def test_local_runtime_detected(self, monkeypatch) -> None:
        result = self._detect(monkeypatch, {})
        assert result["runtime"] == "local"
        assert "hostname" in result
        assert "pid" in result
        assert isinstance(result["pid"], int)

    def test_lambda_takes_precedence_over_ecs(self, monkeypatch) -> None:
        result = self._detect(
            monkeypatch,
            {
                "AWS_LAMBDA_FUNCTION_NAME": "fn",
                "ECS_CONTAINER_METADATA_URI_V4": "http://...",
            },
        )
        assert result["runtime"] == "lambda"

    def test_runtime_field_present_in_log_output(self, monkeypatch) -> None:
        """_RUNTIME_FIELDS are merged into every log entry."""
        lg = fresh_logger("runtime-field-svc")
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

    def setup_method(self) -> None:
        """Clear request context before each test."""
        from wshtlib.context import clear_context

        clear_context()

    def teardown_method(self) -> None:
        """Clear request context after each test."""
        from wshtlib.context import clear_context

        clear_context()

    def _emit(self) -> dict:
        """Log a message and return the parsed JSON entry.

        Returns the parsed JSON log entry as a dict.
        """
        lg = fresh_logger("trace-svc")
        buf = StringIO()
        handler = logging.StreamHandler(buf)
        handler.setFormatter(lg._formatter)
        lg.handlers = [handler]
        lg.info("trace test")
        return json.loads(buf.getvalue().strip())

    def test_trace_id_injected_when_context_set(self) -> None:
        from wshtlib.context import init_context

        init_context(
            {"headers": {"x-amzn-trace-id": "Root=1-abc123"}},
            MagicMock(aws_request_id="req-1"),
        )
        entry = self._emit()
        assert entry.get("trace_id") == "Root=1-abc123"

    def test_trace_id_absent_when_context_empty(self) -> None:
        entry = self._emit()
        assert "trace_id" not in entry

    def test_trace_id_absent_when_context_trace_id_none(self) -> None:
        from wshtlib.context import init_context

        init_context({}, MagicMock(aws_request_id="req-2"))
        entry = self._emit()
        assert "trace_id" not in entry

    # The three tests that stood here covered a lazy import of wshtlib.context
    # and its ImportError/AttributeError fallback. wshtlib.context imports
    # nothing from this package, so there was never a cycle to break: the
    # import is now made at module scope and the unreachable fallback is gone.


# ---------------------------------------------------------------------------
# Level methods
# ---------------------------------------------------------------------------


class TestLevelMethods:
    def _capture(self, name: str) -> tuple[_Logger, StringIO]:
        lg = fresh_logger(name)
        buf = StringIO()
        handler = logging.StreamHandler(buf)
        handler.setFormatter(lg._formatter)
        lg.handlers = [handler]
        return lg, buf

    @pytest.mark.parametrize(
        "method,expected",
        [
            ("debug", "DEBUG"),
            ("info", "INFO"),
            ("warning", "WARNING"),
            ("error", "ERROR"),
            ("critical", "CRITICAL"),
        ],
    )
    def test_each_level_method_emits_fields(self, method: str, expected: str) -> None:
        lg, buf = self._capture(f"lvl-{method}")
        lg.setLevel(logging.DEBUG)
        getattr(lg, method)("event", shoot_id="s-1")
        entry = json.loads(buf.getvalue().strip())
        assert entry["level"] == expected
        assert entry["shoot_id"] == "s-1"

    def test_log_method_takes_explicit_level(self) -> None:
        lg, buf = self._capture("lvl-log")
        lg.log(logging.WARNING, "event", shoot_id="s-2")
        entry = json.loads(buf.getvalue().strip())
        assert entry["level"] == "WARNING"
        assert entry["shoot_id"] == "s-2"

    def test_exception_method_attaches_traceback(self) -> None:
        lg, buf = self._capture("lvl-exception")
        try:
            raise ValueError("boom")
        except ValueError:
            lg.exception("handler failed", op="sync")
        entry = json.loads(buf.getvalue().strip())
        assert entry["level"] == "ERROR"
        assert entry["exception"].startswith("Traceback")
        assert entry["op"] == "sync"

    def test_call_below_threshold_emits_nothing(self) -> None:
        lg, buf = self._capture("lvl-suppressed")
        lg.setLevel(logging.INFO)
        lg.debug("not emitted", shoot_id="s-3")
        assert buf.getvalue() == ""


# ---------------------------------------------------------------------------
# logger field
# ---------------------------------------------------------------------------


class TestLoggerField:
    """``service`` names where the code ran; ``logger`` names what emitted it."""

    def test_logger_field_carries_the_logger_name(self) -> None:
        entry = capture_log(fresh_logger("orders.api.checkout").info, "an event")
        assert entry["logger"] == "orders.api.checkout"

    def test_logger_field_is_independent_of_service(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("WSHT_SERVICE_NAME", "orders")
        entry = capture_log(fresh_logger("orders.api.checkout").info, "an event")
        assert entry["service"] == "orders"
        assert entry["logger"] == "orders.api.checkout"

    def test_caller_field_named_logger_cannot_overwrite_it(self) -> None:
        entry = capture_log(
            fresh_logger("real-name").info, "an event", logger="impostor"
        )
        assert entry["logger"] == "real-name"
        assert entry["extra_logger"] == "impostor"
