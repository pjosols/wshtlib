"""Logs and metrics must agree about which service emitted them.

Before 0.4.0 they could not: ``flush`` read a context key nothing ever wrote, so
every metric was undimensioned, while the logger reported the name passed to
``get_logger``. Both now resolve through ``wshtlib.context.resolve_service``, and
these tests assert the two outputs agree at every step of that chain.
"""

import io
import json
from typing import Optional

import pytest

from tests.conftest import capture_log, fresh_logger
from wshtlib.context import clear_context, set_service
from wshtlib.metrics import MetricsContext

NS = "TestNamespace"
LOGGER_NAME = "orders.api.checkout"


def setup_function() -> None:
    clear_context()


def teardown_function() -> None:
    clear_context()


def logged_service() -> str:
    """Return the ``service`` field of a freshly emitted log line."""
    return capture_log(fresh_logger(LOGGER_NAME).info, "an event")["service"]


def metered_service() -> Optional[str]:
    """Return the ``service`` dimension of a freshly emitted metric blob.

    Returns the dimension value, or ``None`` when the blob carries no service.
    """
    m = MetricsContext(namespace=NS)
    m.count("Event")
    out = io.StringIO()
    m.flush(out)
    return json.loads(out.getvalue()).get("service")


def test_agree_when_set_explicitly() -> None:
    set_service("checkout")
    assert logged_service() == "checkout"
    assert metered_service() == "checkout"


def test_agree_on_the_service_name_env_var(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("WSHT_SERVICE_NAME", "checkout")
    assert logged_service() == "checkout"
    assert metered_service() == "checkout"


def test_agree_on_the_lambda_function_name(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AWS_LAMBDA_FUNCTION_NAME", "orders-prod-checkout")
    assert logged_service() == "orders-prod-checkout"
    assert metered_service() == "orders-prod-checkout"


def test_agree_when_the_context_overrides_the_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AWS_LAMBDA_FUNCTION_NAME", "orders-prod-checkout")
    monkeypatch.setenv("WSHT_SERVICE_NAME", "from-env")
    set_service("from-context")
    assert logged_service() == "from-context"
    assert metered_service() == "from-context"


def test_outside_lambda_the_logger_falls_back_and_metrics_omit() -> None:
    """The one divergence, and it is unavoidable: metrics have no name to borrow.

    With nothing configured the logger still has to say something, so it reports
    the logger's own name. A metric would rather carry no dimension than invent
    one, since a wrong dimension silently forks the time series.
    """
    assert logged_service() == LOGGER_NAME
    assert metered_service() is None
