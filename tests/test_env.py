"""Tests for wshtlib.env"""

import pytest

from wshtlib.env import require_env


def test_require_env_returns_value(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MY_VAR", "hello")
    assert require_env("MY_VAR") == "hello"


def test_require_env_raises_when_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("MY_VAR", raising=False)
    with pytest.raises(RuntimeError, match="MY_VAR"):
        require_env("MY_VAR")


def test_require_env_raises_when_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MY_VAR", "")
    with pytest.raises(RuntimeError, match="MY_VAR"):
        require_env("MY_VAR")
