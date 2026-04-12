# Changelog

## [0.1.0] - 2026-04-12

Initial release. Extracted from wholeshoot2.

### Added
- `MetricsContext` for CloudWatch Embedded Metrics Format (EMF) output
- Module-level `default_metrics` instance for Lambda handlers
- Structured logging with `get_logger()`
- Request context propagation via `ContextVar`
- FastAPI/Starlette middleware for automatic context init and request logging
- Utilities: `require_env()`, `require_https_url()`
- Lambda handler decorator with warming event detection and error handling

### Fixed
- README: corrected decorator name from `lambda_handler` to `bootstrap`
