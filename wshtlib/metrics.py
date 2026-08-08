"""Emit CloudWatch Embedded Metrics Format (EMF) JSON to stdout."""

import json
import os
import sys
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
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

# Keys of the EMF document itself. Metric values are written at the document
# root alongside them, so a metric borrowing one of these names overwrites it:
# a dimension becomes a number where CloudWatch requires a string, or the
# directive describing the whole payload disappears entirely. Either way the
# document is invalid and rejected whole. Named once here and used both to
# reject such a metric and to build the dimensions, so the two cannot drift.
_DIRECTIVE_KEY = "_aws"
_SERVICE_DIMENSION = "service"
_ENVIRONMENT_DIMENSION = "environment"
_RESERVED_METRIC_NAMES = frozenset(
    {_DIRECTIVE_KEY, _SERVICE_DIMENSION, _ENVIRONMENT_DIMENSION}
)


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
        # Guards _metrics. Without it two threads flushing at once both pass
        # the empty check and serialise the same values before either clears,
        # emitting them twice, while a value recorded between one flush's
        # serialisation and its clear is dropped.
        self._lock = threading.Lock()

    def put(self, name: str, value: float, unit: str = "None") -> None:
        """Record a metric value.

        Repeated calls with the same name accumulate rather than replace. When a
        further value would breach an EMF limit, the accumulated metrics are
        flushed first and the value starts a new document.

        name: Metric name.
        value: Numeric value.
        unit: CloudWatch unit string (default ``"None"``).
        Raises ValueError if unit is not a valid CloudWatch unit, if name is a
        reserved EMF document key, or if name was already recorded with a
        different unit.
        """
        if unit not in _VALID_UNITS:
            raise ValueError(
                f"Invalid unit '{unit}'. Must be one of: "
                f"{', '.join(sorted(_VALID_UNITS))}"
            )

        if name in _RESERVED_METRIC_NAMES:
            # Rejected here rather than at flush: put flushes on its own at the
            # EMF limits, so a flush-time check would surface from an unrelated
            # call up to a hundred metrics later, pointing nowhere near the
            # name that caused it. The set is fixed rather than derived from
            # whichever dimensions are currently populated, so a document that
            # validates in CI cannot fail in production.
            raise ValueError(
                f"Metric name '{name}' is a reserved EMF document key "
                f"({', '.join(sorted(_RESERVED_METRIC_NAMES))}) and would "
                f"overwrite it, invalidating the whole document. Rename the metric."
            )

        with self._lock:
            existing = self._metrics.get(name)
            if existing is not None and existing.unit != unit:
                # One MetricDefinition carries one unit. Silently keeping either
                # value would mislabel real measurements, so refuse instead.
                raise ValueError(
                    f"Metric '{name}' is already recorded with unit '{existing.unit}' "
                    f"and cannot also use '{unit}'"
                )

            if self._would_exceed_limit(name):
                self._flush_locked()

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
        with self._lock:
            return self._flush_locked(output)

    def _flush_locked(self, output: Optional[IO[str]] = None) -> Optional[str]:
        """Serialise, write, and clear the accumulated metrics.

        Call with ``self._lock`` held. ``put`` flushes at the EMF limits while
        already holding it, so the locking lives in the public ``flush`` and
        re-entering is structurally impossible rather than merely tolerated.

        output: File-like object to write to, as for ``flush``.
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
            dimensions[_SERVICE_DIMENSION] = service
        if environment:
            dimensions[_ENVIRONMENT_DIMENSION] = environment

        definitions = [
            {"Name": name, "Unit": metric.unit}
            for name, metric in self._metrics.items()
        ]
        values: dict[str, Any] = {
            name: (metric.values[0] if len(metric.values) == 1 else list(metric.values))
            for name, metric in self._metrics.items()
        }

        emf: dict[str, Any] = {
            _DIRECTIVE_KEY: {
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
    return int(datetime.now(timezone.utc).timestamp() * 1000)


# Module-level default context -- suitable for Lambda handlers, where one
# invocation owns the process. It accumulates across everything recording into
# it, and resolves its dimensions when it flushes: under a concurrent server,
# metrics recorded while serving one request can be flushed by another and
# stamped with that request's service. Where per-request attribution matters,
# construct a MetricsContext per request or bind service= up front.
metrics = MetricsContext()
