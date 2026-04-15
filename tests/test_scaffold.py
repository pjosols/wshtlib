"""Tests for package scaffold: pyproject.toml, __init__.py, LICENSE, CHANGELOG."""

import tomllib
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent


# --- pyproject.toml ---


@pytest.fixture()
def pyproject() -> dict:
    with open(ROOT / "pyproject.toml", "rb") as f:
        return tomllib.load(f)


def test_project_name(pyproject: dict) -> None:
    assert pyproject["project"]["name"] == "wshtlib"


def test_project_version(pyproject: dict) -> None:
    import wshtlib
    assert pyproject["project"]["version"] == wshtlib.__version__


def test_requires_python(pyproject: dict) -> None:
    assert pyproject["project"]["requires-python"] == ">=3.13"


def test_license_mit(pyproject: dict) -> None:
    assert pyproject["project"]["license"]["text"] == "MIT"


def test_dependencies_empty(pyproject: dict) -> None:
    assert pyproject["project"]["dependencies"] == []


def test_optional_dep_fastapi(pyproject: dict) -> None:
    fastapi_deps = pyproject["project"]["optional-dependencies"]["fastapi"]
    assert any("starlette" in d for d in fastapi_deps)


def test_urls_present(pyproject: dict) -> None:
    urls = pyproject["project"]["urls"]
    assert "Homepage" in urls
    assert "Repository" in urls
    assert "github.com" in urls["Homepage"]


def test_black_line_length(pyproject: dict) -> None:
    assert pyproject["tool"]["black"]["line-length"] == 88


def test_isort_profile(pyproject: dict) -> None:
    assert pyproject["tool"]["isort"]["profile"] == "black"


def test_ruff_lint_select(pyproject: dict) -> None:
    select = pyproject["tool"]["ruff"]["lint"]["select"]
    assert set(["E", "F", "I", "DTZ"]).issubset(set(select))


def test_mypy_strict(pyproject: dict) -> None:
    assert pyproject["tool"]["mypy"]["strict"] is True


def test_pytest_testpaths(pyproject: dict) -> None:
    assert "tests" in pyproject["tool"]["pytest"]["ini_options"]["testpaths"]


def test_coverage_fail_under(pyproject: dict) -> None:
    assert pyproject["tool"]["coverage"]["report"]["fail_under"] == 90


def test_dev_group_has_required_packages(pyproject: dict) -> None:
    dev_deps = pyproject["dependency-groups"]["dev"]
    required = {
        "pytest",
        "pytest-cov",
        "pytest-asyncio",
        "black",
        "ruff",
        "mypy",
        "httpx",
    }
    dep_names = {d.split(">=")[0].split("==")[0].strip() for d in dev_deps}
    assert required.issubset(dep_names)


# --- __init__.py (source inspection) ---


@pytest.fixture()
def init_text() -> str:
    """Return the content of wshtlib/__init__.py.

    Returns a fresh read of the file for each test.
    """
    return (ROOT / "wshtlib" / "__init__.py").read_text()


def test_version_declared(init_text: str, pyproject: dict) -> None:
    version = pyproject["project"]["version"]
    assert f'__version__ = "{version}"' in init_text


def test_init_exports_context_symbols(init_text: str) -> None:
    for sym in (
        "clear_context",
        "get_context",
        "init_context",
        "init_context_from_request",
        "set_user_id",
    ):
        assert sym in init_text


def test_init_exports_core_symbols(init_text: str) -> None:
    for sym in (
        "bootstrap",
        "require_env",
        "require_https_url",
        "get_logger",
        "set_lambda_context",
        "MetricsContext",
        "metrics",
    ):
        assert sym in init_text


def test_init_middleware_import_is_optional() -> None:
    """Importing wshtlib must not raise even when FastAPI is absent."""
    import importlib
    import sys

    # Remove cached modules so the import is re-evaluated
    for key in list(sys.modules):
        if key.startswith("wshtlib"):
            del sys.modules[key]

    # Simulate missing FastAPI by temporarily hiding the middleware module
    sys.modules["wshtlib.middleware"] = None  # type: ignore[assignment]
    try:
        import wshtlib  # noqa: F401
    finally:
        del sys.modules["wshtlib.middleware"]
        for key in list(sys.modules):
            if key.startswith("wshtlib"):
                del sys.modules[key]
        importlib.import_module("wshtlib")


def test_init_all_list_present(init_text: str) -> None:
    assert "__all__" in init_text


# --- LICENSE ---


def test_license_file_exists() -> None:
    assert (ROOT / "LICENSE").exists()


def test_license_is_mit() -> None:
    try:
        text = (ROOT / "LICENSE").read_text()
    except OSError as exc:
        pytest.fail(f"Could not read LICENSE file: {exc}")
    assert "MIT License" in text
    assert "Wholeshoot" in text


# --- CHANGELOG ---


def test_changelog_exists() -> None:
    assert (ROOT / "CHANGELOG.md").exists()


def test_changelog_has_v010_entry() -> None:
    try:
        text = (ROOT / "CHANGELOG.md").read_text()
    except OSError as exc:
        pytest.fail(f"Could not read CHANGELOG.md: {exc}")
    assert "0.1.0" in text
    assert "Initial release" in text


# --- .gitignore ---


def test_gitignore_exists() -> None:
    assert (ROOT / ".gitignore").exists()


def test_gitignore_entries() -> None:
    text = (ROOT / ".gitignore").read_text()
    for entry in ["dist/", "build/", "__pycache__/", ".venv/", ".coverage", "htmlcov/"]:
        assert entry in text
