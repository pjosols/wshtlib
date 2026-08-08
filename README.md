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

Output is JSON to stdout, enriched with `level`, `timestamp`, `service`, `logger`, `location`, runtime fields, and Lambda context on invocation. `location` names the calling function and line. `logger` is the name passed to `get_logger`; `service` names the deployment unit and is resolved the same way metrics resolve it — see [Service name](#service-name).

Keyword arguments are the preferred spelling, but stdlib's `extra={...}` works too and lands in the same JSON entry; kwargs win if both supply the same key. Fields are also set as attributes on the `LogRecord`, so custom filters and `%(field)s` formatters can read them.

Field names are unrestricted — including `msg`, `args`, and `level`. Only `exc_info`, `extra`, `stack_info`, and `stacklevel` keep their stdlib meanings and cannot be used as fields. A field whose name collides with one the formatter owns (`level`, `message`, `timestamp`, `service`, `logger`, `location`, `trace_id`, `exception`, and the runtime/Lambda fields) is emitted with an `extra_` prefix rather than replacing it:

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

`metrics` is a module-level `MetricsContext` instance, and `@bootstrap`/`@worker` flush it for you when the handler returns. For isolated contexts (e.g. per-request), instantiate `MetricsContext()` directly — one you create yourself is one you flush yourself.

**A namespace is required.** Pass `MetricsContext(namespace=...)` or set `WSHT_METRICS_NAMESPACE`; `flush` raises `RuntimeError` if neither does. It is resolved per flush, so setting the variable after import works.

Recording the same name more than once keeps every value rather than replacing it:

```python
metrics.count("OrderPlaced")
metrics.count("OrderPlaced")
metrics.put("Duration", 50.0, unit="Milliseconds")
metrics.put("Duration", 60.0, unit="Milliseconds")
# {"OrderPlaced": [1.0, 1.0], "Duration": [50.0, 60.0], ...}
```

CloudWatch derives Sum, Average, Minimum, Maximum and SampleCount from those arrays, so a counter's total is its Sum. A name recorded once serialises as a bare number. Recording one name under two different units raises `ValueError` — a single metric definition carries a single unit, and picking one silently would mislabel real measurements.

EMF caps a document at 100 metric definitions and 100 values per metric, and CloudWatch rejects an over-limit document whole — losing every metric in it, not just the one that overflowed. Crossing either limit therefore flushes the accumulated metrics and starts a new document, so `put` may write before you call `flush`.

### Service name

Logging and metrics resolve the service through `resolve_service`, taking the first that supplies a value:

1. an explicit argument — `MetricsContext(service=...)`
2. the request context — `set_service("checkout")`
3. `WSHT_SERVICE_NAME`
4. `AWS_LAMBDA_FUNCTION_NAME`, which Lambda always sets

A log line and a metric emitted from the same context therefore report the same `service`. If nothing supplies a value, logs fall back to the logger's own name and metrics omit the dimension rather than invent one.

Keep dimensions low-cardinality: every unique combination becomes its own CloudWatch metric and bills accordingly.

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

Every variable wshtlib reads is prefixed, so nothing else in the environment can steer it by accident.

| Variable | Default | Description |
|---|---|---|
| `WSHT_LOG_LEVEL` | `INFO` | Logger level |
| `WSHT_METRICS_NAMESPACE` | — | CloudWatch namespace. Required unless passed to `MetricsContext` |
| `WSHT_SERVICE_NAME` | — | `service` dimension and log field, unless set explicitly |
| `WSHT_ENVIRONMENT` | — | Added as a metrics dimension if set |

## Development

```bash
uv sync --group dev
uv run pytest
uv run mypy wshtlib
uv run ruff check wshtlib
```

## License

MIT
