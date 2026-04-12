"""Test require_secret with mocked boto3 and Secrets Manager.

Tests verify secret retrieval, caching, error handling, and security (no secret names in error messages).
"""

import sys
import types
from unittest.mock import MagicMock

import pytest

import wshtlib.secrets as secrets_mod
from wshtlib.secrets import require_secret


def setup_function() -> None:
    secrets_mod._cache.clear()


def _boto3_mocks(
    secret_value: dict | None = None, raise_client_error: bool = False
) -> tuple:
    """Create fake boto3 and botocore modules for testing.

    secret_value: Response dict to return from get_secret_value, or None for empty dict.
    raise_client_error: If True, get_secret_value raises ClientError with ResourceNotFoundException.
    Returns tuple of (modules_dict, mock_client) where modules_dict maps module names to fake modules.
    """
    # Minimal botocore.exceptions mock
    botocore_mod = types.ModuleType("botocore")
    botocore_exc_mod = types.ModuleType("botocore.exceptions")

    class _ClientError(Exception):
        def __init__(self, error_response: dict, operation_name: str) -> None:
            self.response = error_response
            super().__init__(str(error_response))

    botocore_exc_mod.ClientError = _ClientError  # type: ignore[attr-defined]
    botocore_mod.exceptions = botocore_exc_mod  # type: ignore[attr-defined]

    mock_client = MagicMock()
    if raise_client_error:
        mock_client.get_secret_value.side_effect = _ClientError(
            {"Error": {"Code": "ResourceNotFoundException", "Message": "not found"}},
            "GetSecretValue",
        )
    else:
        mock_client.get_secret_value.return_value = secret_value or {}

    boto3_mod = types.ModuleType("boto3")
    boto3_mod.client = MagicMock(return_value=mock_client)  # type: ignore[attr-defined]

    modules = {
        "boto3": boto3_mod,
        "botocore": botocore_mod,
        "botocore.exceptions": botocore_exc_mod,
    }
    return modules, mock_client


def test_returns_secret_string() -> None:
    mods, _ = _boto3_mocks({"SecretString": "s3cr3t"})
    with pytest.MonkeyPatch().context() as mp:
        for k, v in mods.items():
            mp.setitem(sys.modules, k, v)
        assert require_secret("my/secret") == "s3cr3t"


def test_caches_value_on_second_call() -> None:
    mods, mock_client = _boto3_mocks({"SecretString": "cached"})
    with pytest.MonkeyPatch().context() as mp:
        for k, v in mods.items():
            mp.setitem(sys.modules, k, v)
        require_secret("my/secret")
        require_secret("my/secret")
    mock_client.get_secret_value.assert_called_once()


def test_raises_runtime_error_on_client_error() -> None:
    mods, _ = _boto3_mocks(raise_client_error=True)
    with pytest.MonkeyPatch().context() as mp:
        for k, v in mods.items():
            mp.setitem(sys.modules, k, v)
        with pytest.raises(RuntimeError, match="Secret not available"):
            require_secret("my/secret")


def test_raises_runtime_error_when_secret_string_empty() -> None:
    mods, _ = _boto3_mocks({"SecretString": ""})
    with pytest.MonkeyPatch().context() as mp:
        for k, v in mods.items():
            mp.setitem(sys.modules, k, v)
        with pytest.raises(RuntimeError, match="Secret is empty"):
            require_secret("my/secret")


def test_raises_runtime_error_when_secret_string_missing() -> None:
    mods, _ = _boto3_mocks({})
    with pytest.MonkeyPatch().context() as mp:
        for k, v in mods.items():
            mp.setitem(sys.modules, k, v)
        with pytest.raises(RuntimeError, match="Secret is empty"):
            require_secret("my/secret")


def test_client_error_message_does_not_include_secret_name() -> None:
    mods, _ = _boto3_mocks(raise_client_error=True)
    with pytest.MonkeyPatch().context() as mp:
        for k, v in mods.items():
            mp.setitem(sys.modules, k, v)
        with pytest.raises(RuntimeError) as exc_info:
            require_secret("sensitive/secret-name")
    assert "sensitive/secret-name" not in str(exc_info.value)


def test_empty_secret_message_does_not_include_secret_name() -> None:
    mods, _ = _boto3_mocks({"SecretString": ""})
    with pytest.MonkeyPatch().context() as mp:
        for k, v in mods.items():
            mp.setitem(sys.modules, k, v)
        with pytest.raises(RuntimeError) as exc_info:
            require_secret("sensitive/secret-name")
    assert "sensitive/secret-name" not in str(exc_info.value)


def test_exported_from_package() -> None:
    import wshtlib

    assert wshtlib.require_secret is require_secret
    assert "require_secret" in wshtlib.__all__
