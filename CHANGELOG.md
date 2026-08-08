# Changelog

## [0.5.0] - 2026-08-08

### Fixed
- `import wshtlib` no longer fails on a `WSHT_LOG_LEVEL` that is blank or lowercase. The value went straight to `setLevel`, which accepts only the names in its own table, and this package builds a logger at import — so a variable declared but left empty, routine in Terraform and SAM, raised `ValueError` during initialisation and took the function down before a line could be logged. An unusable value now leaves the default in place. The existing default-level test set the level itself before asserting on it, so it never exercised the path.
- `cold_start` is true for every logger on a cold start, not just the first one told about the invocation. The flag was consumed by whichever logger heard first, and this package builds one at import, so it always won — leaving every application logger reporting `false` on a genuine cold start, which is precisely backwards for the latency triage the field exists for. The test that appeared to cover it used a single logger.
- A logger built after the invocation began now carries the Lambda fields too. They were held per logger, so one created inside a handler had no `function_name`, no request id, nothing.
- A metric named `service`, `environment`, or `_aws` is refused with `ValueError` instead of destroying the document. Metric values are written at the root of the embedded metric format document alongside the dimensions and the `_aws` directive, and were written last: such a metric overwrote a dimension with a number where CloudWatch requires a string, or replaced the directive describing the whole payload. CloudWatch rejects the result whole — every metric in it lost, the same failure the format's limits are handled to avoid.
- `MetricsContext` is safe to use from several threads. `flush` serialised its metrics, wrote them, and only then cleared them: a value recorded in that window was dropped, and two threads flushing at once both passed the empty check and serialised the same values, publishing them twice. A double-counted metric is worse than a lost one, nothing about the number looking wrong.
- `set_service` survives the start of a request. `init_context` installed a fresh dictionary, so under `@bootstrap` and `@worker` — which call it on every invocation — a service set during initialisation was silently discarded, and both the log field and the metric dimension fell back to the Lambda function name. No test covered the interaction.
- The X-Ray trace header is found whatever its casing. Only API Gateway's HTTP API lowercases header names; REST APIs and ALBs pass through the client's own casing, so on those the header was missed and `trace_id` quietly became the request id, unjoinable to the trace. Lambda's `_X_AMZN_TRACE_ID` is now consulted as well, which covers event sources that carry no headers at all.
- `@bootstrap` returns 500, and `@worker` logs, for an event that is not the shape they read. Context initialisation ran outside the `try`, so a bare list or a string raised out of the decorator's own setup, past the handling it exists to provide.
- A failing request is logged by the FastAPI middleware. The call to the endpoint was unguarded, so the request most worth having in the access log produced no line at all. It is now logged at error with the status and the traceback, and the exception re-raised so the application's own handlers still decide the response.
- A binary secret is no longer reported as empty. `require_secret` read only `SecretString`, so a secret stored as `SecretBinary` — populated, merely the wrong type — sent the operator looking for the wrong problem.

### Added
- `clear_secret_cache()` discards every cached secret.
- Secrets expire from the cache after `WSHT_SECRET_CACHE_TTL` seconds, 300 by default. A Lambda execution environment outlives a rotation by hours, and a cache with no lifetime and no way to invalidate it went on serving a secret after it stopped working, recovering only when the container happened to be recycled.

### Changed
- The correlation id for a request carrying no `x-correlation-id` is now generated rather than taken from the request path. Every call to `/health` shared the correlation id `"/health"`, so filtering by it returned an unbounded mix of unrelated requests — the opposite of the field's purpose.
- `set_service` is documented as initialisation-time configuration. It is a `ContextVar`, so it does not reach other threads: a `def` endpoint in Starlette's threadpool, anything under `TestClient`, or a call from a lifespan handler will not see it. `WSHT_SERVICE_NAME` is the setting that holds process-wide. As a consequence of the fix above, a value set part-way through an invocation now also persists into later invocations on a warm container.

### Upgrading
- **A metric named `service`, `environment`, or `_aws` now raises.** Such a metric published nothing before — the document carrying it was rejected in full — so no working data is lost, but the call site has to be renamed rather than silently failing.
- **`correlation_id` is a UUID where a request has no `x-correlation-id` header**, in place of the request path. Anything grouping on that value sees a different one.

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
