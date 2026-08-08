"""Emit CloudWatch Embedded Metrics Format (EMF) JSON to stdout."""

import json
import os
import sys
from dataclasses import dataclass, field
from typing import IO, Any, Optional

from wshtlib.context import resolve_service

_VALID_UNITS = {
    "Seconds",
    "Microseconds",
    "Milliseconds",
    "Bytes",
    "Kilobytes",
    "Megabytes",
    "Gigabytes",
    "Terabytes",
    "Bits",
    "Kilobits",
    "Megabits",
    "Gigabits",
    "Terabits",
    "Percent",
    "Count",
    "Bytes/Second",
    "Kilobytes/Second",
    "Megabytes/Second",
    "Gigabytes/Second",
    "Terabytes/Second",
    "Bits/Second",
    "Kilobits/Second",
    "Megabits/Second",
    "Gigabits/Second",
    "Terabits/Second",
    "Count/Second",
    "None",
}

# EMF specification limits. A document that breaks either one is rejected whole,
# so every metric in it is lost -- not just the one that overflowed. The context
# flushes early rather than emitting a document it already knows is invalid.
_MAX_METRIC_DEFINITIONS = 100
_MAX_VALUES_PER_METRIC = 100


@dataclass
class _Metric:
    """One metric name's unit and the values recorded against it."""

    unit: str
    values: list[float] = field(default_factory=list)


class MetricsContext:
    """Accumulates metrics and flushes them as EMF JSON blobs.

    Values are accumulated per name: recording the same name more than once
    keeps every value, and CloudWatch derives Sum, Average, Minimum, Maximum and
    SampleCount from them. A name recorded once serialises as a bare number, a
    name recorded repeatedly as an array.
    """

    def __init__(
        self,
        namespace: Optional[str] = None,
        service: Optional[str] = None,
        output: Optional[IO[str]] = None,
    ) -> None:
        """Create a metrics context.

        namespace: CloudWatch namespace. Falls back to ``WSHT_METRICS_NAMESPACE``;
            ``flush`` raises RuntimeError if neither supplies one.
        service: Value for the ``service`` dimension. Falls back to the shared
            resolution order in ``wshtlib.context.resolve_service``.
        output: Default sink for this context, including automatic flushes at the
            EMF limits. Defaults to ``sys.stdout``.
        """
        self._namespace = namespace
        self._service = service
        self._output = output
        self._metrics: dict[str, _Metric] = {}

    def put(self, name: str, value: float, unit: str = "None") -> None:
        """Record a metric value.

        Repeated calls with the same name accumulate rather than replace. When a
        further value would breach an EMF limit, the accumulated metrics are
        flushed first and the value starts a new document.

        name: Metric name.
        value: Numeric value.
        unit: CloudWatch unit string (default ``"None"``).
        Raises ValueError if unit is not a valid CloudWatch unit, or if name was
        already recorded with a different unit.
        """
        if unit not in _VALID_UNITS:
            raise ValueError(f"Invalid unit '{unit}'. Must be one of {_VALID_UNITS}")

        existing = self._metrics.get(name)
        if existing is not None and existing.unit != unit:
            # One MetricDefinition carries one unit. Silently keeping either
            # value would mislabel real measurements, so refuse instead.
            raise ValueError(
                f"Metric '{name}' is already recorded with unit '{existing.unit}' "
                f"and cannot also use '{unit}'"
            )

        if self._would_exceed_limit(name):
            self.flush()

        metric = self._metrics.setdefault(name, _Metric(unit=unit))
        metric.values.append(float(value))

    def count(self, name: str, value: float = 1.0) -> None:
        """Record a Count-unit observation.

        Repeated calls accumulate; the metric's CloudWatch Sum is the total.

        name: Metric name.
        value: Amount to record (default ``1``).
        """
        self.put(name, value, unit="Count")

    def flush(self, output: Optional[IO[str]] = None) -> Optional[str]:
        """Emit accumulated metrics as an EMF JSON line.

        output: File-like object to write to. Defaults to this context's output,
            then to ``sys.stdout``.
        Returns the serialised EMF JSON string, or ``None`` if no metrics recorded.
        Raises RuntimeError if no CloudWatch namespace is configured.
        """
        if not self._metrics:
            return None

        # Resolved before anything is written or cleared, so a misconfigured
        # namespace fails without discarding the metrics it was carrying.
        namespace = self._resolve_namespace()

        dimensions: dict[str, str] = {}
        service = resolve_service(self._service)
        environment = os.getenv("WSHT_ENVIRONMENT")
        if service:
            dimensions["service"] = service
        if environment:
            dimensions["environment"] = environment

        definitions = [
            {"Name": name, "Unit": metric.unit}
            for name, metric in self._metrics.items()
        ]
        values: dict[str, Any] = {
            name: (metric.values[0] if len(metric.values) == 1 else list(metric.values))
            for name, metric in self._metrics.items()
        }

        emf: dict[str, Any] = {
            "_aws": {
                "Timestamp": _now_ms(),
                "CloudWatchMetrics": [
                    {
                        "Namespace": namespace,
                        "Dimensions": [list(dimensions.keys())] if dimensions else [[]],
                        "Metrics": definitions,
                    }
                ],
            },
            **dimensions,
            **values,
        }
        line = json.dumps(emf)
        (output or self._output or sys.stdout).write(line + "\n")
        self._metrics = {}
        return line

    def _would_exceed_limit(self, name: str) -> bool:
        """Return True if recording another value for name would breach an EMF limit.

        name: Metric name about to receive a value.
        """
        metric = self._metrics.get(name)
        if metric is None:
            return len(self._metrics) >= _MAX_METRIC_DEFINITIONS
        return len(metric.values) >= _MAX_VALUES_PER_METRIC

    def _resolve_namespace(self) -> str:
        """Return the configured CloudWatch namespace.

        Raises RuntimeError if neither the constructor nor the environment set one.
        """
        namespace = self._namespace or os.getenv("WSHT_METRICS_NAMESPACE")
        if not namespace:
            raise RuntimeError(
                "No CloudWatch namespace configured. Pass namespace= to "
                "MetricsContext or set WSHT_METRICS_NAMESPACE."
            )
        return namespace


def _now_ms() -> int:
    """Return current UTC time as milliseconds since epoch."""
    from datetime import datetime, timezone

    return int(datetime.now(timezone.utc).timestamp() * 1000)


# Module-level default context — suitable for Lambda handlers
metrics = MetricsContext()
