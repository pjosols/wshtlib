"""Tests for wshtlib/decorators.py — Lambda handler decorator"""

from unittest.mock import MagicMock, patch

import pytest

from wshtlib.context import clear_context, get_context
from wshtlib.decorators import lambda_handler


@pytest.fixture(autouse=True)
def reset_context():
    clear_context()
    yield
    clear_context()


def _make_lambda_context(request_id: str = "req-test") -> MagicMock:
    ctx = MagicMock()
    ctx.aws_request_id = request_id
    return ctx


# --- warming events ---


def test_warming_event_returns_200():
    @lambda_handler
    def handler(event, context):
        raise AssertionError("should not be called")

    result = handler({"source": "lambda-warming"}, _make_lambda_context())
    assert result == {"statusCode": 200}


def test_warming_event_skips_context_init():
    @lambda_handler
    def handler(event, context):
        pass  # pragma: no cover

    handler({"source": "lambda-warming"}, _make_lambda_context("req-warm"))
    assert get_context() == {}


def test_non_warming_source_does_not_short_circuit():
    called = []

    @lambda_handler
    def handler(event, context):
        called.append(True)
        return {"statusCode": 200}

    handler({"source": "other"}, _make_lambda_context())
    assert called == [True]


# --- context initialisation ---


def test_init_context_called_before_handler():
    captured = {}

    @lambda_handler
    def handler(event, context):
        captured.update(get_context())
        return {}

    event = {"headers": {"x-amzn-trace-id": "Root=1-abc"}}
    handler(event, _make_lambda_context("req-ctx"))
    assert captured["trace_id"] == "Root=1-abc"
    assert captured["correlation_id"] == "req-ctx"


def test_set_lambda_context_called():
    with patch("wshtlib.decorators.set_lambda_context") as mock_set:

        @lambda_handler
        def handler(event, context):
            return {}

        lctx = _make_lambda_context()
        handler({}, lctx)
        mock_set.assert_called_once_with(lctx)


# --- error handling ---


def test_unhandled_exception_returns_500():
    @lambda_handler
    def handler(event, context):
        raise ValueError("boom")

    result = handler({}, _make_lambda_context())
    assert result == {"statusCode": 500}


def test_unhandled_exception_logs_error():
    with patch("wshtlib.decorators.logger") as mock_logger:

        @lambda_handler
        def handler(event, context):
            raise RuntimeError("oops")

        handler({}, _make_lambda_context())
        mock_logger.error.assert_called_once()
        # second positional arg is the function name
        call_args = mock_logger.error.call_args[0]
        assert call_args[1] == "handler"


def test_successful_return_value_passed_through():
    @lambda_handler
    def handler(event, context):
        return {"statusCode": 201, "body": "ok"}

    result = handler({}, _make_lambda_context())
    assert result == {"statusCode": 201, "body": "ok"}


# --- functools.wraps ---


def test_decorator_preserves_function_name():
    @lambda_handler
    def my_special_handler(event, context):
        return {}

    assert my_special_handler.__name__ == "my_special_handler"


def test_decorator_preserves_docstring():
    @lambda_handler
    def handler(event, context):
        """My handler docstring."""
        return {}

    assert handler.__doc__ == "My handler docstring."
