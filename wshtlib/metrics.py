"""Wholeshoot wshtlib - CloudWatch Embedded Metrics Format (EMF) output"""

import json
import os
import sys
from typing import IO, Any, Optional

from wshtlib.context import get_context

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

_NAMESPACE = os.getenv("METRICS_NAMESPACE", "Wholeshoot")


class MetricsContext:
    """Accumulates metrics and flushes as a single EMF JSON blob to stdout."""

    def __init__(self) -> None:
        self._metrics: list[dict[str, str]] = []
        self._values: dict[str, float] = {}

    def put(self, name: str, value: float, unit: str = "None") -> None:
        """Record a metric value.

        name: Metric name.
        value: Numeric value.
        unit: CloudWatch unit string (default ``"None"``).
        Raises ValueError if unit is not a valid CloudWatch unit.
        """
        if unit not in _VALID_UNITS:
            raise ValueError(f"Invalid unit '{unit}'. Must be one of {_VALID_UNITS}")
        self._metrics.append({"Name": name, "Unit": unit})
        self._values[name] = value

    def count(self, name: str, value: float = 1.0) -> None:
        """Increment a Count metric.

        name: Metric name.
        value: Amount to record (default ``1``).
        """
        self.put(name, value, unit="Count")

    def flush(self, output: Optional[IO[str]] = None) -> Optional[str]:
        """Emit accumulated metrics as an EMF JSON line.

        output: File-like object to write to (defaults to ``sys.stdout``).
        Returns the serialised EMF JSON string, or ``None`` if no metrics recorded.
        """
        if not self._metrics:
            return None

        ctx = get_context()
        dimensions: dict[str, str] = {}
        service: Any = ctx.get("service")
        environment = os.getenv("ENVIRONMENT")
        if service:
            dimensions["service"] = service
        if environment:
            dimensions["environment"] = environment

        emf: dict[str, Any] = {
            "_aws": {
                "Timestamp": _now_ms(),
                "CloudWatchMetrics": [
                    {
                        "Namespace": _NAMESPACE,
                        "Dimensions": [list(dimensions.keys())] if dimensions else [[]],
                        "Metrics": self._metrics,
                    }
                ],
            },
            **dimensions,
            **self._values,
        }
        line = json.dumps(emf)
        (output or sys.stdout).write(line + "\n")
        self._metrics = []
        self._values = {}
        return line


def _now_ms() -> int:
    """Return current UTC time as milliseconds since epoch."""
    from datetime import datetime, timezone

    return int(datetime.now(timezone.utc).timestamp() * 1000)


# Module-level default context — suitable for Lambda handlers
metrics = MetricsContext()
