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

`@worker` does the same context init and structured error logging, but it **re-raises** the exception instead of returning a 500. Lambda has to see the invocation fail: retries, `on_failure` destinations, the DLQ, and the `Errors` metric all depend on it. Warming events are not handled.

### Structured logging

```python
from wshtlib import get_logger

logger = get_logger("my-service")
logger.info("user signed in", user_id="u_123", plan="pro")
```

Output is JSON to stderr, keeping stdout clear for EMF metric documents. Each entry includes `level`, `timestamp`, `service`, `logger`, `location` (the calling function and line), runtime fields, and Lambda context during an invocation. `logger` is the name you passed to `get_logger`. `service` names the deployment unit, resolved the same way metrics resolve it — see [Service name](#service-name).

Keyword arguments are the preferred spelling, but stdlib's `extra={...}` works too and lands in the same JSON entry. If both supply the same key, the kwarg wins. Fields are also set as attributes on the `LogRecord`, so custom filters and `%(field)s` formatters can read them — except names that collide with a stdlib record attribute or a reserved name (below), which appear only in the JSON entry.

Almost any field name is allowed, including `msg`, `args`, and `level`. The only exceptions are `exc_info`, `extra`, `stack_info`, and `stacklevel`, which keep their stdlib meanings. If a field name collides with one the formatter itself writes (`level`, `message`, `timestamp`, `service`, `logger`, `location`, `trace_id`, `exception`, and the runtime/Lambda fields), the field is emitted with an `extra_` prefix instead of replacing the formatter's value:

```python
logger.info("subscription renewed", level="premium")
# {"level": "INFO", ..., "message": "subscription renewed", "extra_level": "premium"}
```

Your field still lands in the entry, but it can never overwrite the entry's own metadata.

### CloudWatch metrics (EMF)

```python
from wshtlib.metrics import metrics

metrics.count("OrderPlaced")
metrics.put("Duration", 142.5, unit="Milliseconds")
metrics.flush()
```

`metrics` is a module-level `MetricsContext` instance, and `@bootstrap`/`@worker` flush it for you when the handler returns. For an isolated context (e.g. per-request), instantiate `MetricsContext()` directly. A context you create yourself is one you flush yourself.

A single context is thread-safe: several threads can record into it and flush it at the same time. The catch is attribution. A shared context collects all metrics into one document, and it resolves its dimensions at flush time. In a concurrent server, that means a metric recorded while serving one request can be flushed during another request and stamped with *that* request's `service`. If that matters for your metrics, create a context per request, or pass `service=` when you construct the context so the value never depends on who flushes it.

**A namespace is required.** Pass `MetricsContext(namespace=...)` or set `WSHT_METRICS_NAMESPACE`. If neither is set, `flush` raises `RuntimeError` when there are metrics to write; an empty flush is a no-op. The namespace is resolved on each flush, so setting the variable after import works.

Recording the same name more than once keeps every value rather than replacing it:

```python
metrics.count("OrderPlaced")
metrics.count("OrderPlaced")
metrics.put("Duration", 50.0, unit="Milliseconds")
metrics.put("Duration", 60.0, unit="Milliseconds")
# {"OrderPlaced": [1.0, 1.0], "Duration": [50.0, 60.0], ...}
```

CloudWatch derives Sum, Average, Minimum, Maximum, and SampleCount from those arrays, so a counter's total is its Sum. A name recorded only once serializes as a bare number. Recording one name with two different units raises `ValueError`: a metric definition has exactly one unit, and silently picking one would mislabel real measurements.

Three names are rejected with `ValueError`: `service`, `environment`, and `_aws`. In the EMF document, metric values sit at the root next to the dimensions and the `_aws` directive. A metric with one of those names would overwrite that data, and CloudWatch would then reject the whole document — losing every metric in it, not just the bad one.

EMF also caps a document at 100 metric definitions and 100 values per metric, and again an over-limit document is rejected whole. So when a recording would cross either limit, the context flushes what it has and starts a new document. That means `put` can write output before you ever call `flush`.

### Service name

Logging and metrics resolve the service through `resolve_service`, taking the first that supplies a value:

1. an explicit argument — `MetricsContext(service=...)`
2. the request context — `set_service("checkout")`
3. `WSHT_SERVICE_NAME`
4. `AWS_LAMBDA_FUNCTION_NAME`, which Lambda always sets

A log line and a metric emitted from the same context therefore report the same `service`. If nothing supplies a value, logs fall back to the logger's own name, and metrics simply omit the dimension.

`set_service` is initialization-time configuration. Call it at import, where it survives the context reset that `@bootstrap` and `@worker` perform on every invocation. Because it lives in a `ContextVar`, it does not propagate into threads: a `def` endpoint running in Starlette's threadpool, anything under `TestClient`, and calls made from a FastAPI lifespan handler will not see it. Use `WSHT_SERVICE_NAME` when the value must hold process-wide.

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

Initializes request context, logs `method`, `path`, `status`, `duration_ms` per request, and — when the request carried an `X-Amzn-Trace-Id` header — echoes the trace id back as `X-Trace-Id` on the response.

A request whose handler raises is still logged, at `error` level with `status` 500 and the traceback. The exception is then re-raised so your own exception handlers decide the response. On that path there is no response yet to carry a header, so no `X-Trace-Id` is set.

### Utilities

```python
from wshtlib import require_env, require_https_url, require_secret

db_url = require_env("DATABASE_URL")          # raises RuntimeError if missing/empty
endpoint = require_https_url(require_env("API_URL"))  # raises ValueError if not https
api_key = require_secret("api/key")           # raises RuntimeError if missing/empty, cached
```

Secrets are cached for `WSHT_SECRET_CACHE_TTL` seconds (default 300). The TTL matters because a Lambda execution environment can outlive a secret rotation by hours: a secret cached forever would keep being served after it stops working. Call `clear_secret_cache()` to drop the whole cache immediately.

## Environment variables

Every variable wshtlib reads starts with `WSHT_`, so other environment variables can't affect it by accident.

| Variable | Default | Description |
|---|---|---|
| `WSHT_LOG_LEVEL` | `INFO` | Logger level. Case-insensitive; a blank or unrecognised value leaves the default in place rather than failing the import |
| `WSHT_METRICS_NAMESPACE` | — | CloudWatch namespace. Required unless passed to `MetricsContext` |
| `WSHT_SERVICE_NAME` | — | `service` dimension and log field, unless set explicitly |
| `WSHT_ENVIRONMENT` | — | Added as a metrics dimension if set |
| `WSHT_SECRET_CACHE_TTL` | `300` | Seconds a secret stays cached; `0` disables caching |

## Development

Everything CI runs, in the order it runs it:

```bash
uv sync --group dev
uv run pytest
uv run mypy wshtlib
uv run ruff check wshtlib          # includes flake8-bandit (S) rules
uv run black --check wshtlib tests
uv run zizmor --no-progress .github/workflows/
```

## License

MIT
