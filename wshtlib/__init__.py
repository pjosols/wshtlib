"""Shared runtime library for Wholeshoot services."""

__version__ = "0.1.0"

from wshtlib.context import (
    clear_context,
    get_context,
    init_context,
    init_context_from_request,
    set_user_id,
)
from wshtlib.decorators import lambda_handler
from wshtlib.env import require_env
from wshtlib.http import require_https_url
from wshtlib.logger import get_logger, set_lambda_context
from wshtlib.metrics import MetricsContext
from wshtlib.metrics import metrics as default_metrics

__all__ = [
    "clear_context",
    "get_context",
    "init_context",
    "init_context_from_request",
    "set_user_id",
    "lambda_handler",
    "require_env",
    "require_https_url",
    "get_logger",
    "set_lambda_context",
    "MetricsContext",
    "default_metrics",
]
