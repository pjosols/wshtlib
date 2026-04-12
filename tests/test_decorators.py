"""Tests for wshtlib.decorators"""

import pytest

import wshtlib.logger as logger_mod
from wshtlib.context import clear_context, get_context
from wshtlib.decorators import lambda_handler


@pytest.fixture(autouse=True)
def reset(monkeypatch: pytest.MonkeyPatch) -> None:
    clear_context()
    monkeypatch.setattr(logger_mod, "_cold_start", True)
    logger_mod.logging.Logger.manager.loggerDict.pop("wshtlib.decorators", None)


def _ctx_obj(request_id: str = "req-1") -> object:
    return type("C", (), {"aws_request_id": request_id, "function_name": "fn", "invoked_function_arn": "arn", "memory_limit_in_mb": 128})()


def test_warming_event_returns_200() -> None:
    @lambda_handler
    def handler(event: dict, context: object) -> dict:
        return {"statusCode": 200, "body": "ok"}

    result = handler({"source": "lambda-warming"}, _ctx_obj())
    assert result == {"statusCode": 200}


def test_handler_called_normally() -> None:
    @lambda_handler
    def handler(event: dict, context: object) -> dict:
        return {"statusCode": 200, "body": "ok"}

    result = handler({}, _ctx_obj())
    assert result["statusCode"] == 200


def test_context_initialised_before_handler() -> None:
    captured: list[dict] = []

    @lambda_handler
    def handler(event: dict, context: object) -> dict:
        captured.append(get_context())
        return {"statusCode": 200}

    handler({"headers": {"x-amzn-trace-id": "Root=T"}}, _ctx_obj())
    assert captured[0]["trace_id"] == "Root=T"


def test_unhandled_exception_returns_500() -> None:
    @lambda_handler
    def handler(event: dict, context: object) -> dict:
        raise RuntimeError("boom")

    result = handler({}, _ctx_obj())
    assert result == {"statusCode": 500}


def test_preserves_function_name() -> None:
    @lambda_handler
    def my_handler(event: dict, context: object) -> dict:
        return {"statusCode": 200}

    assert my_handler.__name__ == "my_handler"
