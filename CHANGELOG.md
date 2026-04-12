# Changelog

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
