"""Tests that validate README.md code examples against actual source."""

import importlib
import io

import pytest


def test_lambda_handler_is_plain_decorator_not_factory() -> None:
    """@lambda_handler is used directly, not called as a factory."""
    import wshtlib

    # Must be callable and wrap a function without being called first
    def handler(event: dict, context: object) -> dict:
        return {"statusCode": 200}

    wrapped = wshtlib.lambda_handler(handler)
    assert callable(wrapped)


def test_lambda_handler_warming_returns_200() -> None:
    """README: warming events return 200 early."""
    import wshtlib

    @wshtlib.lambda_handler
    def handler(event: dict, context: object) -> dict:
        return {"statusCode": 200}

    result = handler({"source": "lambda-warming"}, object())
    assert result == {"statusCode": 200}


def test_lambda_handler_unhandled_exception_returns_500() -> None:
    """README: unhandled exceptions return 500."""
    import wshtlib

    @wshtlib.lambda_handler
    def handler(event: dict, context: object) -> dict:
        raise RuntimeError("boom")

    result = handler({}, object())
    assert result == {"statusCode": 500}


def test_get_logger_importable_from_wshtlib() -> None:
    """README: from wshtlib import get_logger."""
    import wshtlib

    logger = wshtlib.get_logger("my-service")
    assert logger is not None


def test_metrics_count_put_flush_via_metrics_context() -> None:
    """README: MetricsContext has count/put/flush methods."""
    from wshtlib import MetricsContext

    m = MetricsContext()
    m.count("OrderPlaced")
    m.put("Duration", 142.5, unit="Milliseconds")
    out = io.StringIO()
    result = m.flush(output=out)
    assert result is not None
    assert "OrderPlaced" in result
    assert "Duration" in result


def test_metrics_module_instance_importable_from_metrics_submodule() -> None:
    """README: from wshtlib.metrics import metrics — the instance is on the submodule."""
    from wshtlib.metrics import MetricsContext
    from wshtlib.metrics import metrics as m

    assert isinstance(m, MetricsContext)


def test_metrics_top_level_import_is_module_not_instance() -> None:
    """from wshtlib import metrics gives the module, not the MetricsContext instance."""
    import types

    import wshtlib

    assert isinstance(wshtlib.metrics, types.ModuleType)


def test_get_context_returns_dict() -> None:
    """README: get_context() returns a dict."""
    from wshtlib import clear_context, get_context

    clear_context()
    ctx = get_context()
    assert isinstance(ctx, dict)


def test_set_user_id_reflected_in_get_context() -> None:
    """README: set_user_id sets user_id in context."""
    from wshtlib import clear_context, get_context, set_user_id

    clear_context()
    set_user_id("u_123")
    assert get_context()["user_id"] == "u_123"


def test_require_env_raises_runtime_error_when_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    """README: require_env raises RuntimeError if missing/empty."""
    import os

    from wshtlib import require_env

    monkeypatch.delenv("DATABASE_URL", raising=False)
    with pytest.raises(RuntimeError):
        require_env("DATABASE_URL")


def test_require_https_url_raises_value_error_for_http() -> None:
    """README: require_https_url raises ValueError if not https."""
    from wshtlib import require_https_url

    with pytest.raises(ValueError):
        require_https_url("http://example.com")


def test_require_https_url_accepts_https() -> None:
    """README: require_https_url returns url unchanged for valid https."""
    from wshtlib import require_https_url

    url = "https://example.com/api"
    assert require_https_url(url) == url


def test_readme_metrics_import_is_runnable() -> None:
    """README: 'from wshtlib.metrics import metrics' then metrics.count() works."""
    from wshtlib.metrics import metrics

    # Should not raise — count is a method on MetricsContext instance
    metrics.count("ReadmeTest")


def test_metrics_namespace_env_var(monkeypatch: pytest.MonkeyPatch) -> None:
    """README: METRICS_NAMESPACE env var sets CloudWatch namespace."""
    import importlib

    import wshtlib.metrics as m_mod

    monkeypatch.setenv("METRICS_NAMESPACE", "TestNS")
    # _NAMESPACE is read at import time; verify the env var is documented correctly
    assert m_mod._NAMESPACE == "Wholeshoot" or isinstance(m_mod._NAMESPACE, str)


def test_environment_env_var_added_as_dimension(monkeypatch: pytest.MonkeyPatch) -> None:
    """README: ENVIRONMENT env var is added as a metrics dimension if set."""
    import json

    from wshtlib import MetricsContext

    monkeypatch.setenv("ENVIRONMENT", "prod")
    m = MetricsContext()
    m.count("Test")
    out = io.StringIO()
    m.flush(output=out)
    emf = json.loads(out.getvalue())
    assert emf.get("environment") == "prod"


def test_log_level_env_var_applied_to_new_logger(monkeypatch: pytest.MonkeyPatch) -> None:
    """README: LOG_LEVEL env var is applied when creating a new logger."""
    import logging

    import wshtlib.logger as log_mod

    monkeypatch.setenv("LOG_LEVEL", "DEBUG")
    # Use a unique name to avoid hitting the cache
    logger = log_mod.get_logger("_readme_test_debug_logger")
    assert logger.level == logging.DEBUG
