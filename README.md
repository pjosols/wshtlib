# wshtlib

Lightweight observability library for AWS Lambda and FastAPI. Zero external dependencies.

A focused alternative to [aws-powertools](https://github.com/aws-powertools/powertools-lambda-python) — covers structured logging, CloudWatch metrics (EMF), request context propagation, and Lambda handler boilerplate. Nothing more.

## Install

```bash
pip install wshtlib
```

FastAPI/Starlette middleware is optional:

```bash
pip install wshtlib[fastapi]
```

## Usage

### Lambda handler

Two decorators, one per invocation mode.

`@bootstrap` — **synchronous** invocations (API Gateway), where the return value is the response:

```python
from wshtlib import bootstrap, get_logger

logger = get_logger("my-service")

@bootstrap
def handler(event, context):
    logger.info("invoked", path=event.get("path"))
    return {"statusCode": 200}
```

It handles:
- Warming events (`"source": "lambda-warming"`) — returns 200 early
- Context init and structured log enrichment
- Unhandled exceptions — logs error, returns 500

`@worker` — **asynchronous** invocations (S3, EventBridge, SQS), where the return value is discarded:

```python
from wshtlib import worker, get_logger

logger = get_logger("my-worker")

@worker
def handler(event, context):
    logger.info("processing", records=len(event["Records"]))
```

Same context init and structured error logging, but the exception is **re-raised** rather than swallowed — retries, `on_failure` destinations, the DLQ, and the `Errors` metric all depend on Lambda seeing the invocation fail. No warming-event handling.

### Structured logging

```python
from wshtlib import get_logger

logger = get_logger("my-service")
logger.info("user signed in", user_id="u_123", plan="pro")
```

Output is JSON to stdout, enriched with `level`, `timestamp`, `service`, `location`, runtime fields, and Lambda context on invocation. `location` names the calling function and line.

Keyword arguments are the preferred spelling, but stdlib's `extra={...}` works too and lands in the same JSON entry; kwargs win if both supply the same key. Fields are also set as attributes on the `LogRecord`, so custom filters and `%(field)s` formatters can read them.

Field names are unrestricted — including `msg`, `args`, and `level`. Only `exc_info`, `extra`, `stack_info`, and `stacklevel` keep their stdlib meanings and cannot be used as fields. A field whose name collides with one the formatter owns (`level`, `message`, `timestamp`, `service`, `location`, `trace_id`, `exception`, and the runtime/Lambda fields) is emitted with an `extra_` prefix rather than replacing it:

```python
logger.info("subscription renewed", level="premium")
# {"level": "INFO", ..., "message": "subscription renewed", "extra_level": "premium"}
```

This keeps an enrichment field from falsifying the record it was meant to enrich.

### CloudWatch metrics (EMF)

```python
from wshtlib.metrics import metrics

metrics.count("OrderPlaced")
metrics.put("Duration", 142.5, unit="Milliseconds")
metrics.flush()
```

`metrics` is a module-level `MetricsContext` instance. For isolated contexts (e.g. per-request), instantiate `MetricsContext()` directly.

Namespace defaults to the `METRICS_NAMESPACE` env var, falling back to `"Wholeshoot"`.

### Request context

```python
from wshtlib import get_context, set_user_id

set_user_id(claims["sub"])
ctx = get_context()  # {"trace_id": ..., "correlation_id": ..., "user_id": ...}
```

Context is stored in a `ContextVar` — safe for concurrent async handlers.

### FastAPI middleware

```python
from fastapi import FastAPI
from wshtlib.middleware import WshtlibMiddleware

app = FastAPI()
app.add_middleware(WshtlibMiddleware)
```

Initialises request context, logs `method`, `path`, `status`, `duration_ms` per request, and injects `X-Trace-Id` into the response.

### Utilities

```python
from wshtlib import require_env, require_https_url, require_secret

db_url = require_env("DATABASE_URL")          # raises RuntimeError if missing/empty
endpoint = require_https_url(require_env("API_URL"))  # raises ValueError if not https
api_key = require_secret("api/key")           # raises RuntimeError if missing/empty, cached
```

## Environment variables

| Variable | Default | Description |
|---|---|---|
| `LOG_LEVEL` | `INFO` | Logger level |
| `METRICS_NAMESPACE` | `Wholeshoot` | CloudWatch namespace |
| `ENVIRONMENT` | — | Added as a metrics dimension if set |

## Development

```bash
uv sync --group dev
uv run pytest
uv run mypy wshtlib
uv run ruff check wshtlib
```

## License

MIT
