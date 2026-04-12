"""Tests for wshtlib.metrics"""

import json
import io

import pytest

from wshtlib.context import clear_context
from wshtlib.metrics import MetricsContext, _NAMESPACE


@pytest.fixture(autouse=True)
def reset() -> None:
    clear_context()


def test_put_and_flush_returns_json() -> None:
    mc = MetricsContext()
    mc.put("Latency", 42.0, "Milliseconds")
    out = io.StringIO()
    line = mc.flush(out)
    assert line is not None
    data = json.loads(line)
    assert data["Latency"] == 42.0


def test_flush_emf_structure() -> None:
    mc = MetricsContext()
    mc.put("Errors", 1.0, "Count")
    out = io.StringIO()
    line = mc.flush(out)
    assert line is not None
    data = json.loads(line)
    aws = data["_aws"]
    assert aws["CloudWatchMetrics"][0]["Namespace"] == _NAMESPACE
    assert {"Name": "Errors", "Unit": "Count"} in aws["CloudWatchMetrics"][0]["Metrics"]


def test_flush_writes_to_output() -> None:
    mc = MetricsContext()
    mc.count("Hits")
    out = io.StringIO()
    mc.flush(out)
    assert out.getvalue().strip() != ""


def test_flush_returns_none_when_empty() -> None:
    mc = MetricsContext()
    assert mc.flush() is None


def test_flush_resets_metrics() -> None:
    mc = MetricsContext()
    mc.count("X")
    out = io.StringIO()
    mc.flush(out)
    assert mc.flush(out) is None


def test_count_uses_count_unit() -> None:
    mc = MetricsContext()
    mc.count("Invocations", 3.0)
    out = io.StringIO()
    line = mc.flush(out)
    assert line is not None
    data = json.loads(line)
    assert data["Invocations"] == 3.0
    metrics_list = data["_aws"]["CloudWatchMetrics"][0]["Metrics"]
    assert {"Name": "Invocations", "Unit": "Count"} in metrics_list


def test_put_invalid_unit_raises() -> None:
    mc = MetricsContext()
    with pytest.raises(ValueError, match="Invalid unit"):
        mc.put("X", 1.0, "Bananas")


def test_flush_includes_service_dimension(monkeypatch: pytest.MonkeyPatch) -> None:
    from wshtlib.context import _ctx
    _ctx.set({"service": "my-svc", "trace_id": None, "correlation_id": None, "user_id": None})
    mc = MetricsContext()
    mc.count("X")
    out = io.StringIO()
    line = mc.flush(out)
    assert line is not None
    data = json.loads(line)
    assert data.get("service") == "my-svc"


def test_flush_includes_environment_dimension(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ENVIRONMENT", "prod")
    mc = MetricsContext()
    mc.count("X")
    out = io.StringIO()
    line = mc.flush(out)
    assert line is not None
    data = json.loads(line)
    assert data.get("environment") == "prod"
