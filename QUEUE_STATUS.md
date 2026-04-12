# Queue Status — wshtlib

Last rendered: 2026-04-12 18:34:11 UTC

## Pending

### Scaffold pyproject.toml and package structure
**Status:** pending  **Stage:** queued  **Priority:** 10

Create the standalone package scaffold for wshtlib:

1. `pyproject.toml` with:
   - `[project]` metadata: name="wshtlib", version="0.1.0", description, author, license="MIT", requires-python=">=3.13", dependencies=[]
   - `[project.optional-dependencies]` fastapi = ["starlette>=0.27"]
   - `[project.urls]` Homepage, Repository pointing to github.com/polsen/wshtlib (or whatever gh creates)
   - `[tool.black]` line-length=88
   - `[tool.isort]` profile="black"
   - `[tool.ruff.lint]` select=["E","F","I","DTZ"]
   - `[tool.mypy]` strict=true
   - `[tool.pytest.ini_options]` testpaths=["tests"], addopts="--tb=short -q"
   - `[tool.coverage.report]` fail_under=90
   - dev dependency group: pytest, pytest-cov, pytest-asyncio, black, ruff, mypy, starlette, httpx

2. `wshtlib/__init__.py` — export the full public API and set `__version__ = "0.1.0"`:
   ```python
   from wshtlib.context import clear_context, get_context, init_context, init_context_from_request, set_user_id
   from wshtlib.decorators import lambda_handler
   from wshtlib.env import require_env
   from wshtlib.http import require_https_url
   from wshtlib.logger import get_logger, set_lambda_context
   from wshtlib.metrics import MetricsContext, metrics
   ```
   WshtlibMiddleware is NOT exported from __init__ (optional dep — import directly from wshtlib.middleware).

3. `LICENSE` — MIT license text, copyright holder "Wholeshoot"

4. `CHANGELOG.md` — initial entry for v0.1.0: "Initial release. Extracted from wholeshoot2."

5. `.gitignore` — standard Python gitignore (dist/, build/, *.egg-info/, __pycache__/, .venv/, .coverage, htmlcov/)

Do NOT copy the source modules yet — that's a separate task.

### Copy and clean source modules from wholeshoot2
**Status:** pending  **Stage:** queued  **Priority:** 9

Copy the 7 source modules from `../wholeshoot2/backend/v1/wshtlib/` into `wshtlib/` in this project. Files to copy:
- context.py
- logger.py
- metrics.py
- decorators.py
- middleware.py
- env.py
- http.py

After copying, apply these fixes:
1. `logger.py`: the bare `except Exception` in `_get_trace_id` is acceptable (it's a best-effort trace injection in a formatter — document why with a comment). All other exception handling is already specific.
2. `middleware.py`: the `except ImportError` is intentional — add a comment explaining it's a graceful optional-dep skip.
3. All files: verify all public functions have Wholeshoot-style docstrings (summary line, then `param: description` lines, Returns, Raises). Fix any that use Args/Returns Google style instead.
4. Run `uv run black wshtlib/` and `uv run ruff check wshtlib/` — fix any issues.
5. Run `uv run mypy wshtlib/` — fix any strict type errors.

Do NOT modify logic — only style/type fixes.

### Port and clean test suite from wholeshoot2
**Status:** pending  **Stage:** queued  **Priority:** 8

Port the 5 existing wshtlib test files from `../wholeshoot2/backend/v1/tests/` into `tests/` in this project.

Source files:
- test_wshtlib_context.py → tests/test_context.py
- test_wshtlib_logger.py → tests/test_logger.py
- test_wshtlib_metrics.py → tests/test_metrics.py
- test_wshtlib_decorators.py → tests/test_decorators.py
- test_wshtlib_middleware.py → tests/test_middleware.py

Also create:
- tests/test_env.py — tests for `require_env` (missing var, empty var, present var)
- tests/test_http.py — tests for `require_https_url` (valid https, http rejected, ftp rejected, empty hostname rejected, empty string rejected)
- tests/__init__.py — empty

For each ported file:
1. Remove ALL `sys.path.insert` lines
2. Remove ALL `import context as ctx_module` / `import logger as logger_module` style imports — replace with `from wshtlib.X import ...`
3. Keep all test logic identical — do not add or remove tests
4. Verify `setup_function` / fixtures still reset module-level state correctly (e.g. `clear_context()`, `_cold_start` reset via monkeypatch or direct assignment)

Run `uv run pytest tests/ -q` — all tests must pass before committing.

### Add GitHub Actions CI and PyPI publish workflows
**Status:** pending  **Stage:** queued  **Priority:** 7

Create `.github/workflows/ci.yml` — runs on every push and PR to main:

```yaml
name: CI
on:
  push:
    branches: [main]
  pull_request:
    branches: [main]

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v4
        with:
          python-version: "3.13"
      - run: uv sync --group dev
      - run: uv run ruff check wshtlib tests
      - run: uv run black --check wshtlib tests
      - run: uv run mypy wshtlib
      - run: uv run pytest --cov=wshtlib --cov-report=term-missing --cov-fail-under=90
```

Also create `.github/workflows/publish.yml` — triggers on push of version tags (`v*.*.*`):

```yaml
name: Publish to PyPI
on:
  push:
    tags: ["v*.*.*"]

jobs:
  publish:
    runs-on: ubuntu-latest
    environment: pypi
    permissions:
      id-token: write
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v4
        with:
          python-version: "3.13"
      - run: uv build
      - uses: pypa/gh-action-pypi-publish@release/v1
```

Use PyPI trusted publishing (OIDC) — no API token needed in secrets.

### Create GitHub repo and push initial release
**Status:** pending  **Stage:** queued  **Priority:** 6

Create the GitHub repo and push the initial commit.

Steps:
1. Run `gh repo create wshtlib --public --description "Lightweight observability library for AWS Lambda and FastAPI. Zero external dependencies." --source=. --remote=origin --push`
   - If that fails (repo already exists), just add the remote and push: `git remote add origin https://github.com/<user>/wshtlib.git && git push -u origin main`
2. Verify the push succeeded: `gh repo view wshtlib`
3. Tag the initial release: `git tag v0.1.0 && git push origin v0.1.0`

Note: `gh` CLI is available. Use the authenticated user's account. The repo name is `wshtlib`.

### Update wholeshoot2 to consume wshtlib from PyPI
**Status:** pending  **Stage:** queued  **Priority:** 5

Update `../wholeshoot2` to consume `wshtlib` from PyPI instead of the local copy.

Steps:
1. In `../wholeshoot2/pyproject.toml`, add `wshtlib>=0.1.0` to the `base` dependency group (so all Lambda handlers and services get it automatically).
2. Delete `../wholeshoot2/backend/v1/wshtlib/` directory entirely (all 8 files).
3. Delete `../wholeshoot2/backend/v1/tests/test_wshtlib_*.py` (5 files) — these tests now live in the wshtlib repo.
4. Run `uv sync --group dev` in `../wholeshoot2/` to verify the dependency resolves.
5. Run `uv run pytest backend/v1/tests/ -q --ignore=backend/v1/tests/test_wshtlib_context.py` (already deleted) to verify nothing broke.

Important: all imports in wholeshoot2 already use `from wshtlib.X import Y` — no import changes needed. The only change is the source of the package (PyPI vs local directory).
