"""Test CloudWatch Embedded Metrics Format output."""

import io
import json

from wshtlib.context import clear_context
from wshtlib.metrics import _NAMESPACE, MetricsContext


def setup_function() -> None:
    clear_context()


# --- put ---


def test_put_records_metric() -> None:
    m = MetricsContext()
    m.put("Latency", 42.0, "Milliseconds")
    out = io.StringIO()
    line = m.flush(out)
    data = json.loads(line)
    metrics_list = data["_aws"]["CloudWatchMetrics"][0]["Metrics"]
    assert {"Name": "Latency", "Unit": "Milliseconds"} in metrics_list
    assert data["Latency"] == 42.0


def test_put_invalid_unit_raises() -> None:
    m = MetricsContext()
    try:
        m.put("X", 1.0, "Bananas")
        assert False, "expected ValueError"
    except ValueError as e:
        assert "Bananas" in str(e)


# --- count ---


def test_count_uses_count_unit() -> None:
    m = MetricsContext()
    m.count("Errors")
    out = io.StringIO()
    line = m.flush(out)
    data = json.loads(line)
    assert {"Name": "Errors", "Unit": "Count"} in data["_aws"]["CloudWatchMetrics"][0][
        "Metrics"
    ]
    assert data["Errors"] == 1.0


def test_count_custom_value() -> None:
    m = MetricsContext()
    m.count("Uploads", 5.0)
    out = io.StringIO()
    line = m.flush(out)
    data = json.loads(line)
    assert data["Uploads"] == 5.0


# --- flush ---


def test_flush_returns_none_when_empty() -> None:
    m = MetricsContext()
    assert m.flush() is None


def test_flush_writes_to_stdout_by_default(capsys) -> None:
    m = MetricsContext()
    m.count("Hits")
    m.flush()
    captured = capsys.readouterr()
    data = json.loads(captured.out.strip())
    assert data["Hits"] == 1.0


def test_flush_clears_metrics() -> None:
    m = MetricsContext()
    m.count("X")
    out = io.StringIO()
    m.flush(out)
    assert m.flush(out) is None  # nothing left


def test_flush_emf_structure() -> None:
    m = MetricsContext()
    m.put("Duration", 100.0, "Milliseconds")
    out = io.StringIO()
    line = m.flush(out)
    data = json.loads(line)
    aws = data["_aws"]
    assert "Timestamp" in aws
    assert isinstance(aws["Timestamp"], int)
    cw = aws["CloudWatchMetrics"][0]
    assert cw["Namespace"] == _NAMESPACE
    assert "Dimensions" in cw
    assert "Metrics" in cw


def test_flush_namespace_from_env(monkeypatch) -> None:
    import wshtlib.metrics as metrics_mod

    monkeypatch.setattr(metrics_mod, "_NAMESPACE", "MyApp")
    m = MetricsContext()
    m.count("X")
    out = io.StringIO()
    line = m.flush(out)
    data = json.loads(line)
    assert data["_aws"]["CloudWatchMetrics"][0]["Namespace"] == "MyApp"


# --- dimensions from context ---


def test_flush_includes_service_dimension_from_context() -> None:
    import wshtlib.context as wc

    wc._ctx.set(
        {"trace_id": None, "correlation_id": None, "user_id": None, "service": "api"}
    )

    m = MetricsContext()
    m.count("Req")
    out = io.StringIO()
    line = m.flush(out)
    data = json.loads(line)
    assert data.get("service") == "api"
    dim_keys = data["_aws"]["CloudWatchMetrics"][0]["Dimensions"][0]
    assert "service" in dim_keys


def test_flush_includes_environment_dimension(monkeypatch) -> None:
    monkeypatch.setenv("ENVIRONMENT", "prod")
    m = MetricsContext()
    m.count("X")
    out = io.StringIO()
    line = m.flush(out)
    data = json.loads(line)
    assert data.get("environment") == "prod"
    dim_keys = data["_aws"]["CloudWatchMetrics"][0]["Dimensions"][0]
    assert "environment" in dim_keys


def test_flush_empty_dimensions_when_no_context(monkeypatch) -> None:
    monkeypatch.delenv("ENVIRONMENT", raising=False)
    clear_context()
    m = MetricsContext()
    m.count("X")
    out = io.StringIO()
    line = m.flush(out)
    data = json.loads(line)
    # Dimensions should be [[]] when no service/environment
    assert data["_aws"]["CloudWatchMetrics"][0]["Dimensions"] == [[]]


# --- multiple metrics ---


def test_multiple_metrics_in_single_flush() -> None:
    m = MetricsContext()
    m.put("Latency", 50.0, "Milliseconds")
    m.count("Errors")
    out = io.StringIO()
    line = m.flush(out)
    data = json.loads(line)
    names = [entry["Name"] for entry in data["_aws"]["CloudWatchMetrics"][0]["Metrics"]]
    assert "Latency" in names
    assert "Errors" in names
    assert data["Latency"] == 50.0
    assert data["Errors"] == 1.0


# --- package-level import shadowing ---


def test_wshtlib_metrics_attribute_is_module() -> None:
    """wshtlib.metrics must resolve to the submodule, not the MetricsContext class."""
    import types

    import wshtlib
    import wshtlib.metrics

    assert isinstance(wshtlib.metrics, types.ModuleType)


def test_wshtlib_default_metrics_is_metrics_context_instance() -> None:
    """wshtlib.default_metrics must be a MetricsContext instance."""
    import wshtlib

    assert isinstance(wshtlib.default_metrics, MetricsContext)
