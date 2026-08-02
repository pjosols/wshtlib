# Changelog

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
