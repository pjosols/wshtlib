"""Test CloudWatch Embedded Metrics Format output."""

import io
import json
from typing import Any

import jsonschema
import pytest

from tests.conftest import EMF_SCHEMA
from wshtlib.context import clear_context, set_service
from wshtlib.metrics import (
    _MAX_METRIC_DEFINITIONS,
    _MAX_VALUES_PER_METRIC,
    MetricsContext,
)

NS = "TestNamespace"


def setup_function() -> None:
    clear_context()


def emit(m: MetricsContext) -> dict[str, Any]:
    """Flush a context and return the parsed, spec-validated EMF document.

    m: The metrics context to flush.
    Returns the parsed EMF document.
    """
    out = io.StringIO()
    line = m.flush(out)
    assert line is not None
    data = json.loads(line)
    jsonschema.validate(instance=data, schema=EMF_SCHEMA)
    return data


def directive(data: dict[str, Any]) -> dict[str, Any]:
    """Return the single MetricDirective from a parsed EMF document.

    data: A parsed EMF document.
    """
    return data["_aws"]["CloudWatchMetrics"][0]


# --- put ---


def test_put_records_metric() -> None:
    m = MetricsContext(namespace=NS)
    m.put("Latency", 42.0, "Milliseconds")
    data = emit(m)
    assert {"Name": "Latency", "Unit": "Milliseconds"} in directive(data)["Metrics"]
    assert data["Latency"] == 42.0


def test_put_invalid_unit_raises() -> None:
    m = MetricsContext(namespace=NS)
    with pytest.raises(ValueError, match="Bananas"):
        m.put("X", 1.0, "Bananas")


def test_put_conflicting_unit_for_same_name_raises() -> None:
    """One MetricDefinition carries one unit, so the second spelling is refused."""
    m = MetricsContext(namespace=NS)
    m.put("Payload", 1.0, "Bytes")
    with pytest.raises(ValueError, match="already recorded with unit 'Bytes'"):
        m.put("Payload", 2.0, "Count")


def test_put_conflicting_unit_does_not_record_the_value() -> None:
    m = MetricsContext(namespace=NS)
    m.put("Payload", 1.0, "Bytes")
    with pytest.raises(ValueError):
        m.put("Payload", 2.0, "Count")
    assert emit(m)["Payload"] == 1.0


# --- count ---


def test_count_uses_count_unit() -> None:
    m = MetricsContext(namespace=NS)
    m.count("Errors")
    data = emit(m)
    assert {"Name": "Errors", "Unit": "Count"} in directive(data)["Metrics"]
    assert data["Errors"] == 1.0


def test_count_custom_value() -> None:
    m = MetricsContext(namespace=NS)
    m.count("Uploads", 5.0)
    assert emit(m)["Uploads"] == 5.0


def test_repeated_count_accumulates_every_value() -> None:
    """The regression this release exists for: count() used to report the last value.

    Five increments emitted five duplicate definitions and a single value of 1.
    """
    m = MetricsContext(namespace=NS)
    for _ in range(5):
        m.count("Errors")
    data = emit(m)
    assert data["Errors"] == [1.0, 1.0, 1.0, 1.0, 1.0]
    assert directive(data)["Metrics"] == [{"Name": "Errors", "Unit": "Count"}]


def test_repeated_count_with_values_sums_in_cloudwatch() -> None:
    """CloudWatch's Sum over the array is the total the caller counted."""
    m = MetricsContext(namespace=NS)
    m.count("Items", 3.0)
    m.count("Items", 4.0)
    assert sum(emit(m)["Items"]) == 7.0


# --- accumulation ---


def test_repeated_put_keeps_every_sample() -> None:
    m = MetricsContext(namespace=NS)
    m.put("Latency", 50.0, "Milliseconds")
    m.put("Latency", 60.0, "Milliseconds")
    assert emit(m)["Latency"] == [50.0, 60.0]


def test_single_value_serialises_as_a_scalar() -> None:
    """A lone observation stays a bare number, not a one-element array."""
    m = MetricsContext(namespace=NS)
    m.put("Latency", 42.0, "Milliseconds")
    assert emit(m)["Latency"] == 42.0


def test_one_definition_per_name_however_often_recorded() -> None:
    m = MetricsContext(namespace=NS)
    for _ in range(10):
        m.put("Latency", 1.0, "Milliseconds")
    assert len(directive(emit(m))["Metrics"]) == 1


def test_multiple_metrics_in_single_flush() -> None:
    m = MetricsContext(namespace=NS)
    m.put("Latency", 50.0, "Milliseconds")
    m.count("Errors")
    data = emit(m)
    names = [entry["Name"] for entry in directive(data)["Metrics"]]
    assert names == ["Latency", "Errors"]
    assert data["Latency"] == 50.0
    assert data["Errors"] == 1.0


def test_integer_values_are_recorded_as_floats() -> None:
    m = MetricsContext(namespace=NS)
    m.put("Bytes", 12, "Bytes")
    assert emit(m)["Bytes"] == 12.0


# --- EMF limits ---


def test_exceeding_values_per_metric_flushes_early() -> None:
    """A 101-member array would be rejected whole, losing every metric with it."""
    out = io.StringIO()
    m = MetricsContext(namespace=NS, output=out)
    for _ in range(_MAX_VALUES_PER_METRIC + 1):
        m.count("Hits")
    m.flush()

    blobs = [json.loads(line) for line in out.getvalue().strip().split("\n")]
    assert len(blobs) == 2
    assert len(blobs[0]["Hits"]) == _MAX_VALUES_PER_METRIC
    assert blobs[1]["Hits"] == 1.0


def test_exceeding_metric_definitions_flushes_early() -> None:
    out = io.StringIO()
    m = MetricsContext(namespace=NS, output=out)
    for i in range(_MAX_METRIC_DEFINITIONS + 1):
        m.count(f"Metric{i}")
    m.flush()

    blobs = [json.loads(line) for line in out.getvalue().strip().split("\n")]
    assert len(blobs) == 2
    assert len(blobs[0]["_aws"]["CloudWatchMetrics"][0]["Metrics"]) == (
        _MAX_METRIC_DEFINITIONS
    )
    assert len(blobs[1]["_aws"]["CloudWatchMetrics"][0]["Metrics"]) == 1


def test_no_value_is_lost_across_an_automatic_flush() -> None:
    out = io.StringIO()
    m = MetricsContext(namespace=NS, output=out)
    total = _MAX_VALUES_PER_METRIC * 2 + 7
    for _ in range(total):
        m.count("Hits")
    m.flush()

    recorded = 0
    for line in out.getvalue().strip().split("\n"):
        value = json.loads(line)["Hits"]
        recorded += len(value) if isinstance(value, list) else 1
    assert recorded == total


def test_automatic_flush_output_validates_against_the_spec() -> None:
    out = io.StringIO()
    m = MetricsContext(namespace=NS, output=out)
    for _ in range(_MAX_VALUES_PER_METRIC + 1):
        m.count("Hits")
    m.flush()
    for line in out.getvalue().strip().split("\n"):
        jsonschema.validate(instance=json.loads(line), schema=EMF_SCHEMA)


# --- namespace ---


def test_namespace_from_constructor() -> None:
    m = MetricsContext(namespace="Explicit")
    m.count("X")
    assert directive(emit(m))["Namespace"] == "Explicit"


def test_namespace_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("WSHT_METRICS_NAMESPACE", "FromEnv")
    m = MetricsContext()
    m.count("X")
    assert directive(emit(m))["Namespace"] == "FromEnv"


def test_namespace_env_is_read_at_flush_not_import(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Resolution happens per flush, so the variable can be set after import."""
    m = MetricsContext()
    m.count("X")
    monkeypatch.setenv("WSHT_METRICS_NAMESPACE", "SetLate")
    assert directive(emit(m))["Namespace"] == "SetLate"


def test_constructor_namespace_wins_over_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("WSHT_METRICS_NAMESPACE", "FromEnv")
    m = MetricsContext(namespace="Explicit")
    m.count("X")
    assert directive(emit(m))["Namespace"] == "Explicit"


def test_missing_namespace_raises() -> None:
    m = MetricsContext()
    m.count("X")
    with pytest.raises(RuntimeError, match="WSHT_METRICS_NAMESPACE"):
        m.flush(io.StringIO())


def test_missing_namespace_does_not_discard_the_metrics() -> None:
    """The failure is configuration, so the measurements survive it."""
    m = MetricsContext()
    m.count("X")
    with pytest.raises(RuntimeError):
        m.flush(io.StringIO())

    m._namespace = NS
    assert emit(m)["X"] == 1.0


def test_missing_namespace_is_silent_when_nothing_was_recorded() -> None:
    assert MetricsContext().flush(io.StringIO()) is None


# --- flush ---


def test_flush_returns_none_when_empty() -> None:
    assert MetricsContext(namespace=NS).flush(io.StringIO()) is None


def test_flush_writes_to_stdout_by_default(capsys: pytest.CaptureFixture[str]) -> None:
    m = MetricsContext(namespace=NS)
    m.count("Hits")
    m.flush()
    assert json.loads(capsys.readouterr().out.strip())["Hits"] == 1.0


def test_flush_writes_to_the_context_output() -> None:
    out = io.StringIO()
    m = MetricsContext(namespace=NS, output=out)
    m.count("Hits")
    m.flush()
    assert json.loads(out.getvalue().strip())["Hits"] == 1.0


def test_flush_argument_overrides_the_context_output() -> None:
    context_out, call_out = io.StringIO(), io.StringIO()
    m = MetricsContext(namespace=NS, output=context_out)
    m.count("Hits")
    m.flush(call_out)
    assert context_out.getvalue() == ""
    assert json.loads(call_out.getvalue().strip())["Hits"] == 1.0


def test_flush_clears_metrics() -> None:
    out = io.StringIO()
    m = MetricsContext(namespace=NS)
    m.count("X")
    m.flush(out)
    assert m.flush(out) is None


def test_flush_emf_structure() -> None:
    m = MetricsContext(namespace=NS)
    m.put("Duration", 100.0, "Milliseconds")
    data = emit(m)
    assert isinstance(data["_aws"]["Timestamp"], int)
    cw = directive(data)
    assert cw["Namespace"] == NS
    assert "Dimensions" in cw
    assert "Metrics" in cw


# --- dimensions ---


def test_service_dimension_from_set_service() -> None:
    set_service("media-api")
    m = MetricsContext(namespace=NS)
    m.count("Req")
    data = emit(m)
    assert data["service"] == "media-api"
    assert "service" in directive(data)["Dimensions"][0]


def test_service_dimension_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("WSHT_SERVICE_NAME", "from-env")
    m = MetricsContext(namespace=NS)
    m.count("Req")
    assert emit(m)["service"] == "from-env"


def test_service_dimension_falls_back_to_the_lambda_function_name(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AWS_LAMBDA_FUNCTION_NAME", "some-function")
    m = MetricsContext(namespace=NS)
    m.count("Req")
    assert emit(m)["service"] == "some-function"


def test_service_resolution_precedence(monkeypatch: pytest.MonkeyPatch) -> None:
    """Explicit beats context beats WSHT_SERVICE_NAME beats the function name."""
    monkeypatch.setenv("AWS_LAMBDA_FUNCTION_NAME", "function")
    monkeypatch.setenv("WSHT_SERVICE_NAME", "env")
    set_service("context")

    m = MetricsContext(namespace=NS, service="explicit")
    m.count("Req")
    assert emit(m)["service"] == "explicit"

    m = MetricsContext(namespace=NS)
    m.count("Req")
    assert emit(m)["service"] == "context"

    clear_context()
    m = MetricsContext(namespace=NS)
    m.count("Req")
    assert emit(m)["service"] == "env"

    monkeypatch.delenv("WSHT_SERVICE_NAME")
    m = MetricsContext(namespace=NS)
    m.count("Req")
    assert emit(m)["service"] == "function"


def test_environment_dimension(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("WSHT_ENVIRONMENT", "prod")
    m = MetricsContext(namespace=NS)
    m.count("X")
    data = emit(m)
    assert data["environment"] == "prod"
    assert "environment" in directive(data)["Dimensions"][0]


def test_empty_dimensions_when_nothing_resolves() -> None:
    m = MetricsContext(namespace=NS)
    m.count("X")
    assert directive(emit(m))["Dimensions"] == [[]]


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
