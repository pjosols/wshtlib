"""Tests that validate README.md code examples against actual source."""

import io

import pytest


def test_bootstrap_is_plain_decorator_not_factory() -> None:
    """@bootstrap is used directly, not called as a factory."""
    import wshtlib

    # Must be callable and wrap a function without being called first
    def handler(event: dict, context: object) -> dict:
        return {"statusCode": 200}

    wrapped = wshtlib.bootstrap(handler)
    assert callable(wrapped)


def test_bootstrap_warming_returns_200() -> None:
    """README: warming events return 200 early."""
    import wshtlib

    @wshtlib.bootstrap
    def handler(event: dict, context: object) -> dict:
        return {"statusCode": 200}

    result = handler({"source": "lambda-warming"}, object())
    assert result == {"statusCode": 200}


def test_bootstrap_unhandled_exception_returns_500() -> None:
    """README: unhandled exceptions return 500."""
    import wshtlib

    @wshtlib.bootstrap
    def handler(event: dict, context: object) -> dict:
        raise RuntimeError("boom")

    result = handler({}, object())
    assert result == {"statusCode": 500}


def test_worker_is_plain_decorator_not_factory() -> None:
    """@worker is used directly, not called as a factory."""
    import wshtlib

    def handler(event: dict, context: object) -> None:
        return None

    wrapped = wshtlib.worker(handler)
    assert callable(wrapped)


def test_worker_unhandled_exception_propagates() -> None:
    """README: @worker re-raises so Lambda records the failure."""
    import wshtlib

    @wshtlib.worker
    def handler(event: dict, context: object) -> None:
        raise RuntimeError("boom")

    with pytest.raises(RuntimeError):
        handler({}, object())


def test_get_logger_importable_from_wshtlib() -> None:
    """README: from wshtlib import get_logger."""
    import wshtlib

    logger = wshtlib.get_logger("my-service")
    assert logger is not None


def test_metrics_count_put_flush_via_metrics_context() -> None:
    """README: MetricsContext has count/put/flush methods."""
    from wshtlib import MetricsContext

    m = MetricsContext(namespace="OrderService")
    m.count("OrderPlaced")
    m.put("Duration", 142.5, unit="Milliseconds")
    out = io.StringIO()
    result = m.flush(output=out)
    assert "OrderPlaced" in result
    assert "Duration" in result


def test_metrics_module_instance_importable_from_metrics_submodule() -> None:
    """README: from wshtlib.metrics import metrics — instance is on the submodule."""
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


def test_require_env_raises_runtime_error_when_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """README: require_env raises RuntimeError if missing/empty."""

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


def test_readme_metrics_import_is_runnable(monkeypatch: pytest.MonkeyPatch) -> None:
    """README: 'from wshtlib.metrics import metrics' then metrics.count() works."""
    from wshtlib.metrics import metrics

    monkeypatch.setenv("WSHT_METRICS_NAMESPACE", "ReadmeNS")
    metrics.count("ReadmeTest")
    # Drain the module-level instance so the recording does not leak into
    # another test through the decorators' flush-on-exit.
    assert metrics.flush(io.StringIO()) is not None


def test_metrics_namespace_env_var(monkeypatch: pytest.MonkeyPatch) -> None:
    """README: WSHT_METRICS_NAMESPACE sets the CloudWatch namespace."""
    import json

    from wshtlib import MetricsContext

    monkeypatch.setenv("WSHT_METRICS_NAMESPACE", "TestNS")
    m = MetricsContext()
    m.count("Test")
    out = io.StringIO()
    m.flush(output=out)
    emf = json.loads(out.getvalue())
    assert emf["_aws"]["CloudWatchMetrics"][0]["Namespace"] == "TestNS"


def test_metrics_namespace_is_required() -> None:
    """README: a flush with no namespace configured raises."""
    from wshtlib import MetricsContext

    m = MetricsContext()
    m.count("Test")
    with pytest.raises(RuntimeError):
        m.flush(output=io.StringIO())


def test_environment_env_var_added_as_dimension(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """README: WSHT_ENVIRONMENT is added as a metrics dimension if set."""
    import json

    from wshtlib import MetricsContext

    monkeypatch.setenv("WSHT_ENVIRONMENT", "prod")
    m = MetricsContext(namespace="TestNS")
    m.count("Test")
    out = io.StringIO()
    m.flush(output=out)
    emf = json.loads(out.getvalue())
    assert emf.get("environment") == "prod"


def test_service_name_env_var_added_as_dimension(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """README: WSHT_SERVICE_NAME is added as the service dimension."""
    import json

    from wshtlib import MetricsContext

    monkeypatch.setenv("WSHT_SERVICE_NAME", "orders")
    m = MetricsContext(namespace="TestNS")
    m.count("Test")
    out = io.StringIO()
    m.flush(output=out)
    assert json.loads(out.getvalue()).get("service") == "orders"


def test_set_service_is_exported(monkeypatch: pytest.MonkeyPatch) -> None:
    """README: set_service overrides the resolved service name."""
    from wshtlib import clear_context, resolve_service, set_service

    clear_context()
    monkeypatch.setenv("WSHT_SERVICE_NAME", "from-env")
    set_service("explicit")
    assert resolve_service() == "explicit"
    clear_context()


def test_log_level_env_var_applied_to_new_logger(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """README: WSHT_LOG_LEVEL is applied when creating a new logger."""
    import logging

    import wshtlib.logger as log_mod

    monkeypatch.setenv("WSHT_LOG_LEVEL", "DEBUG")
    # Use a unique name to avoid hitting the cache
    logger = log_mod.get_logger("_readme_test_debug_logger")
    assert logger.level == logging.DEBUG


def test_reserved_metric_names_are_refused() -> None:
    """README: service, environment and _aws are refused as metric names."""
    from wshtlib import MetricsContext

    m = MetricsContext(namespace="ReadmeNS")
    for name in ("service", "environment", "_aws"):
        with pytest.raises(ValueError):
            m.put(name, 1.0)


def test_clear_secret_cache_is_exported() -> None:
    """README: clear_secret_cache() discards the cache at once."""
    import wshtlib
    import wshtlib.secrets as secrets_mod

    secrets_mod._cache["readme/secret"] = (float("inf"), "value")
    wshtlib.clear_secret_cache()
    assert secrets_mod._cache == {}
    assert "clear_secret_cache" in wshtlib.__all__


def test_unusable_log_level_leaves_the_default_in_place(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """README: a blank or unrecognised WSHT_LOG_LEVEL does not fail the import."""
    import logging

    import wshtlib.logger as log_mod

    monkeypatch.setenv("WSHT_LOG_LEVEL", "")
    assert log_mod.get_logger("_readme_test_blank_level").level == logging.INFO
