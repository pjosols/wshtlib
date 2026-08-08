# Changelog

## [0.4.0] - 2026-08-08

### Fixed
- `count(...)` now counts. Recording a name repeatedly appended a duplicate metric definition each time while overwriting the single stored value, so five increments emitted five identical definitions and a value of `1`. Values now accumulate per name, and each name contributes exactly one definition. No test covered a repeated name — the existing multi-metric test used two different names, which is how it survived.
- The `service` dimension is no longer always absent. `flush` read a context key that nothing in the library ever wrote, so every document was emitted undimensioned — meaning two functions publishing the same metric name wrote to the same time series. The test that appeared to cover it constructed the key by hand.
- Documents can no longer exceed the embedded metric format's limits of 100 metric definitions and 100 values per metric. CloudWatch rejects an over-limit document whole, discarding every metric in it; crossing either limit now flushes and starts a new document instead.
- The metrics namespace is read at flush time rather than at import. As a module-level constant it could not be set after import, or exercised by a test.

### Added
- `set_service(...)` sets the service name on the request context, and `resolve_service(...)` exposes the resolution order: explicit argument, request context, `WSHT_SERVICE_NAME`, then `AWS_LAMBDA_FUNCTION_NAME`.
- `MetricsContext(namespace=..., service=..., output=...)`. `output` sets the context's default sink, including for the automatic flushes at the format's limits.
- Log entries carry a `logger` field holding the name passed to `get_logger`.
- `@bootstrap` and `@worker` flush the module-level metrics context when the handler returns, on both the success and the failure path. A failure to flush is logged rather than raised, so it cannot replace the handler's own outcome. A `MetricsContext` you create yourself is still yours to flush.

### Changed
- Logging and metrics resolve `service` through the same chain, so a log line and a metric emitted from the same context agree. Previously the logger reported the name given to `get_logger` while metrics reported nothing at all.
- A metric name recorded more than once serialises as an array of values; a name recorded once still serialises as a bare number. CloudWatch derives Sum, Average, Minimum, Maximum and SampleCount from the array.
- Recording one metric name under two different units raises `ValueError`. A single metric definition carries a single unit, so silently keeping one would mislabel real measurements.
- A namespace is now required. `flush` raises `RuntimeError` when neither the constructor nor `WSHT_METRICS_NAMESPACE` supplies one, rather than falling back to a default that suited only the library's original consumer.
- Every environment variable the library reads is now prefixed `WSHT_`. Unprefixed names like `SERVICE_NAME` and `ENVIRONMENT` are easily set by something else in the same process, and one of them feeds a metric dimension.

### Upgrading
Five changes are visible from outside, and three of them fail open — producing working software with the wrong configuration rather than an error:

- **Rename the environment variables**: `LOG_LEVEL` → `WSHT_LOG_LEVEL`, `ENVIRONMENT` → `WSHT_ENVIRONMENT`, `METRICS_NAMESPACE` → `WSHT_METRICS_NAMESPACE`, `SERVICE_NAME` → `WSHT_SERVICE_NAME`. The old names are not consulted; missing one silently leaves the default in place.
- **Set a namespace.** A flush without one raises where it previously used a built-in default. This one fails loudly.
- **`service` in log output changes meaning.** It now names the deployment unit — under Lambda, the function name — where it previously held the argument to `get_logger`. That argument is still emitted, in the new `logger` field. Dashboards, metric filters, and saved queries keying on `service` will see a different value.
- **Repeated metric names serialise as arrays.** Anything parsing the emitted JSON should expect either a number or a list of numbers.
- **`put` may write to stdout** before `flush` is called, when a document reaches the format's limits.

## [0.3.0] - 2026-08-02

### Fixed
- `get_logger(...)` now emits fields passed as `extra={...}`, the stdlib spelling. They were previously set on the `LogRecord` and then ignored by the JSON formatter, which serializes only the kwargs it stashes in `_extra_keys` — the line still logged, silently stripped of the context that made it worth logging.
- `location` now names the calling function and line. It previously resolved to wshtlib's own `_log` frame on every line, because the wrapper added a stack frame without adjusting `stacklevel` — making the field useless for triage.
- Fields named `msg`, `args`, or `level` no longer raise `TypeError` at the call site. These shadowed parameters of the internal `_log` wrapper, so a logging call could take down the request it was logging.
- An `extra` key colliding with a `LogRecord` attribute (`module`, `name`, `message`) no longer raises `KeyError` from stdlib's reserved-name check.
- `logger.info("event", field=...)` type-checks under mypy. The library previously declared no typed signatures for the keyword spelling it documents, so mypy rejected it with `call-arg` and left `extra={...}` — the spelling that dropped fields — as the only one that passed.

### Changed
- A field whose name collides with one the formatter owns (`level`, `message`, `timestamp`, `service`, `location`, `trace_id`, `exception`, and the runtime/Lambda fields) is now emitted under an `extra_` prefix instead of overwriting it. Previously such a field replaced the formatter's value, so `extra={"level": "DEBUG"}` produced an INFO line indexed as DEBUG and `extra={"message": ...}` replaced the message outright. Collision handling is now uniform across all owned keys; `exception` previously resolved the opposite way, silently discarding the caller's value.
- Precedence between the two spellings is unchanged: keyword arguments win a key collision with `extra`.

### Upgrading
Log output changes in three ways that dashboards, metric filters, and alerts may key on:
- `location` values change from `_log:<line>` to `<caller>:<line>`.
- Fields colliding with an owned key move to an `extra_` prefix.
- Fields passed via `extra={...}` now appear in the JSON entry at all.

## [0.2.0] - 2026-08-02

### Added
- `@worker` — Lambda decorator for asynchronous invocations (S3, EventBridge, SQS). Same context init and structured error logging as `@bootstrap`, but re-raises so Lambda records the failure: retries, `on_failure` destinations, DLQ routing, and the `Errors` metric all depend on the exception propagating. No warming-event handling.

## [0.1.2] - 2026-04-15

### Changed
- `WshtlibMiddleware` is now importable directly from `wshtlib` top-level package, with graceful fallback when FastAPI is not installed

## [0.1.1] - 2026-04-12

### Fixed
- Add `readme` field to `pyproject.toml` so PyPI renders the project description

## [0.1.0] - 2026-04-12

Initial release.

### Features
- Structured JSON logging (`get_logger`) with Lambda context and runtime enrichment
- CloudWatch EMF metrics (`MetricsContext`, `metrics`) with namespace and dimension support
- Request context propagation via `ContextVar` (`init_context`, `get_context`, `set_user_id`)
- Lambda handler decorator (`@bootstrap`) with warming event detection and error boundary
- FastAPI/Starlette middleware for automatic context init and request logging (`WshtlibMiddleware`)
- AWS Secrets Manager helper (`require_secret`) with cold-start caching
- Utilities: `require_env`, `require_https_url`
