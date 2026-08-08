"""Structured logging, EMF metrics, and request context for AWS Lambda."""

__version__ = "0.4.0"

from wshtlib.context import (
    clear_context,
    get_context,
    init_context,
    init_context_from_request,
    resolve_service,
    set_service,
    set_user_id,
)
from wshtlib.decorators import bootstrap, worker
from wshtlib.env import require_env
from wshtlib.http import require_https_url
from wshtlib.logger import get_logger, set_lambda_context
from wshtlib.metrics import MetricsContext
from wshtlib.metrics import metrics as default_metrics
from wshtlib.secrets import require_secret

__all__ = [
    "clear_context",
    "get_context",
    "init_context",
    "init_context_from_request",
    "resolve_service",
    "set_service",
    "set_user_id",
    "bootstrap",
    "worker",
    "require_env",
    "require_https_url",
    "get_logger",
    "set_lambda_context",
    "MetricsContext",
    "default_metrics",
    "require_secret",
]

try:
    from wshtlib.middleware import WshtlibMiddleware

    __all__ += ["WshtlibMiddleware"]
except ImportError:
    pass
