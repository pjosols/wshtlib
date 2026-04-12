# Changelog

## [Unreleased]

### Added
- `require_secret()` for AWS Secrets Manager integration with caching and error handling
- Test module docstrings: concise, imperative descriptions for `test_logger.py`, `test_metrics.py`, `test_middleware.py`, `test_readme.py`, `test_scaffold.py`, `test_secrets.py`

### Docs
- Updated `__init__.py` module docstring for clarity
- Refined module docstrings in `wshtlib.metrics` and `wshtlib.middleware` to be concise and imperative

## [0.1.0] - 2026-04-12

Initial release.

### Added
- `MetricsContext` for CloudWatch Embedded Metrics Format (EMF) output
- Module-level `default_metrics` instance for Lambda handlers
- Structured logging with `get_logger()` — JSON output with runtime and Lambda context enrichment
- Request context propagation via `ContextVar`
- FastAPI/Starlette middleware for automatic context init and request logging
- Utilities: `require_env()`, `require_https_url()`
- Lambda handler decorator with warming event detection and error handling
- Comprehensive test suite for logger: JSON output structure, Lambda context enrichment, runtime detection, and trace ID injection
- Module docstrings and Wholeshoot-style function docstrings for all public APIs

### Fixed
- README: corrected decorator name from `lambda_handler` to `bootstrap`
