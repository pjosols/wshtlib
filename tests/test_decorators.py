"""Test Lambda handler decorator."""

import json
from io import StringIO
from unittest.mock import MagicMock, patch

import pytest

from wshtlib.context import clear_context, get_context
from wshtlib.decorators import bootstrap, default_metrics, worker


@pytest.fixture(autouse=True)
def reset_context() -> None:
    clear_context()
    yield
    clear_context()


def _make_lambda_context(request_id: str = "req-test") -> MagicMock:
    ctx = MagicMock()
    ctx.aws_request_id = request_id
    return ctx


# --- warming events ---


def test_warming_event_returns_200() -> None:
    @bootstrap
    def handler(event, context):
        raise AssertionError("should not be called")

    result = handler({"source": "lambda-warming"}, _make_lambda_context())
    assert result == {"statusCode": 200}


def test_warming_event_skips_context_init() -> None:
    @bootstrap
    def handler(event, context):
        pass  # pragma: no cover

    handler({"source": "lambda-warming"}, _make_lambda_context("req-warm"))
    assert get_context() == {}


def test_non_warming_source_does_not_short_circuit() -> None:
    called = []

    @bootstrap
    def handler(event, context):
        called.append(True)
        return {"statusCode": 200}

    handler({"source": "other"}, _make_lambda_context())
    assert called == [True]


# --- context initialisation ---


def test_init_context_called_before_handler() -> None:
    captured = {}

    @bootstrap
    def handler(event, context):
        captured.update(get_context())
        return {}

    event = {"headers": {"x-amzn-trace-id": "Root=1-abc"}}
    handler(event, _make_lambda_context("req-ctx"))
    assert captured["trace_id"] == "Root=1-abc"
    assert captured["correlation_id"] == "req-ctx"


def test_set_lambda_context_called() -> None:
    with patch("wshtlib.decorators.set_lambda_context") as mock_set:

        @bootstrap
        def handler(event, context):
            return {}

        lctx = _make_lambda_context()
        handler({}, lctx)
        mock_set.assert_called_once_with(lctx)


# --- error handling ---


def test_unhandled_exception_returns_500() -> None:
    @bootstrap
    def handler(event, context):
        raise ValueError("boom")

    result = handler({}, _make_lambda_context())
    assert result == {"statusCode": 500}


def test_unhandled_exception_logs_error() -> None:
    with patch("wshtlib.decorators.logger") as mock_logger:

        @bootstrap
        def handler(event, context):
            raise RuntimeError("oops")

        handler({}, _make_lambda_context())
        mock_logger.error.assert_called_once()
        call_args = mock_logger.error.call_args[0]
        assert call_args[1] == "handler"


def test_successful_return_value_passed_through() -> None:
    @bootstrap
    def handler(event, context):
        return {"statusCode": 201, "body": "ok"}

    result = handler({}, _make_lambda_context())
    assert result == {"statusCode": 201, "body": "ok"}


# --- functools.wraps ---


def test_decorator_preserves_function_name() -> None:
    @bootstrap
    def my_special_handler(event, context):
        return {}

    assert my_special_handler.__name__ == "my_special_handler"


def test_decorator_preserves_docstring() -> None:
    @bootstrap
    def handler(event, context):
        """My handler docstring."""
        return {}

    assert handler.__doc__ == "My handler docstring."


# --- public API ---


def test_bootstrap_exported_from_wshtlib() -> None:
    import wshtlib

    assert hasattr(wshtlib, "bootstrap")
    assert callable(wshtlib.bootstrap)


def test_lambda_handler_not_exported_from_wshtlib() -> None:
    import wshtlib

    assert not hasattr(wshtlib, "lambda_handler")


def test_bootstrap_in_all() -> None:
    import wshtlib

    assert "bootstrap" in wshtlib.__all__


def test_lambda_handler_not_in_all() -> None:
    import wshtlib

    assert "lambda_handler" not in wshtlib.__all__


# --- @worker: async invocation mode ---


def test_worker_re_raises_unhandled_exception() -> None:
    @worker
    def handler(event, context):
        raise ValueError("boom")

    with pytest.raises(ValueError, match="boom"):
        handler({}, _make_lambda_context())


def test_worker_logs_error_before_re_raising() -> None:
    with patch("wshtlib.decorators.logger") as mock_logger:

        @worker
        def handler(event, context):
            raise RuntimeError("oops")

        with pytest.raises(RuntimeError):
            handler({}, _make_lambda_context())

        mock_logger.error.assert_called_once()
        call_args = mock_logger.error.call_args[0]
        assert call_args[1] == "handler"
        assert mock_logger.error.call_args[1]["exc_info"] is True


def test_worker_does_not_short_circuit_warming_events() -> None:
    called = []

    @worker
    def handler(event, context):
        called.append(event)
        return None

    handler({"source": "lambda-warming"}, _make_lambda_context())
    assert called == [{"source": "lambda-warming"}]


def test_worker_init_context_called_before_handler() -> None:
    captured = {}

    @worker
    def handler(event, context):
        captured.update(get_context())

    event = {"headers": {"x-amzn-trace-id": "Root=1-def"}}
    handler(event, _make_lambda_context("req-worker"))
    assert captured["trace_id"] == "Root=1-def"
    assert captured["correlation_id"] == "req-worker"


def test_worker_set_lambda_context_called() -> None:
    with patch("wshtlib.decorators.set_lambda_context") as mock_set:

        @worker
        def handler(event, context):
            return None

        lctx = _make_lambda_context()
        handler({}, lctx)
        mock_set.assert_called_once_with(lctx)


def test_worker_successful_return_value_passed_through() -> None:
    @worker
    def handler(event, context):
        return {"processed": 3}

    assert handler({}, _make_lambda_context()) == {"processed": 3}


def test_worker_preserves_function_metadata() -> None:
    @worker
    def my_worker_handler(event, context):
        """My worker docstring."""

    assert my_worker_handler.__name__ == "my_worker_handler"
    assert my_worker_handler.__doc__ == "My worker docstring."


def test_worker_exported_from_wshtlib() -> None:
    import wshtlib

    assert callable(wshtlib.worker)
    assert "worker" in wshtlib.__all__


# --- metrics flushed on the way out ---


@pytest.fixture
def metrics_output(monkeypatch: pytest.MonkeyPatch) -> StringIO:
    """Drain the module-level metrics context and redirect it to a buffer."""
    default_metrics._metrics.clear()
    buf = StringIO()
    monkeypatch.setattr(default_metrics, "_output", buf)
    monkeypatch.setenv("WSHT_METRICS_NAMESPACE", "TestNS")
    yield buf
    default_metrics._metrics.clear()


def test_bootstrap_flushes_metrics_recorded_by_the_handler(
    metrics_output: StringIO,
) -> None:
    @bootstrap
    def handler(event, context):
        default_metrics.count("Handled")
        return {"statusCode": 200}

    assert handler({}, _make_lambda_context()) == {"statusCode": 200}
    assert json.loads(metrics_output.getvalue().strip())["Handled"] == 1.0


def test_bootstrap_flushes_metrics_even_when_the_handler_raises(
    metrics_output: StringIO,
) -> None:
    """The measurements taken before the failure are the ones worth having."""

    @bootstrap
    def handler(event, context):
        default_metrics.count("Attempted")
        raise ValueError("boom")

    assert handler({}, _make_lambda_context()) == {"statusCode": 500}
    assert json.loads(metrics_output.getvalue().strip())["Attempted"] == 1.0


def test_worker_flushes_metrics_before_re_raising(metrics_output: StringIO) -> None:
    @worker
    def handler(event, context):
        default_metrics.count("Attempted")
        raise ValueError("boom")

    with pytest.raises(ValueError, match="boom"):
        handler({}, _make_lambda_context())
    assert json.loads(metrics_output.getvalue().strip())["Attempted"] == 1.0


def test_no_output_when_the_handler_recorded_nothing(
    metrics_output: StringIO,
) -> None:
    @bootstrap
    def handler(event, context):
        return {"statusCode": 200}

    handler({}, _make_lambda_context())
    assert metrics_output.getvalue() == ""


def test_a_failing_flush_does_not_fail_a_successful_invocation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A missing namespace is a configuration error, not a request failure."""
    default_metrics._metrics.clear()
    monkeypatch.setattr(default_metrics, "_output", StringIO())

    @bootstrap
    def handler(event, context):
        default_metrics.count("Handled")
        return {"statusCode": 200}

    assert handler({}, _make_lambda_context()) == {"statusCode": 200}
    default_metrics._metrics.clear()


def test_a_failing_flush_does_not_mask_the_handler_exception(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    default_metrics._metrics.clear()
    monkeypatch.setattr(default_metrics, "_output", StringIO())

    @worker
    def handler(event, context):
        default_metrics.count("Attempted")
        raise ValueError("the real problem")

    with pytest.raises(ValueError, match="the real problem"):
        handler({}, _make_lambda_context())
    default_metrics._metrics.clear()


def test_a_failing_flush_is_logged() -> None:
    with patch("wshtlib.decorators.logger") as mock_logger:

        @bootstrap
        def handler(event, context):
            default_metrics.count("Handled")
            return {"statusCode": 200}

        handler({}, _make_lambda_context())

    assert mock_logger.error.called
    assert "flush metrics" in mock_logger.error.call_args[0][0]
    default_metrics._metrics.clear()
