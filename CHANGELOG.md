# Changelog

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
