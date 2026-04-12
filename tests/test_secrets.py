"""Test require_secret with mocked boto3 and Secrets Manager."""

import sys
import types
import pytest
from unittest.mock import MagicMock

import wshtlib.secrets as secrets_mod
from wshtlib.secrets import require_secret


def setup_function() -> None:
    secrets_mod._cache.clear()


def _boto3_mocks(secret_value: dict | None = None, raise_client_error: bool = False) -> tuple:
    """Return (sys_modules_patch, mock_client) with boto3 and botocore faked."""
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
        with pytest.raises(RuntimeError, match="Secret not available: my/secret"):
            require_secret("my/secret")


def test_raises_runtime_error_when_secret_string_empty() -> None:
    mods, _ = _boto3_mocks({"SecretString": ""})
    with pytest.MonkeyPatch().context() as mp:
        for k, v in mods.items():
            mp.setitem(sys.modules, k, v)
        with pytest.raises(RuntimeError, match="Secret is empty: my/secret"):
            require_secret("my/secret")


def test_raises_runtime_error_when_secret_string_missing() -> None:
    mods, _ = _boto3_mocks({})
    with pytest.MonkeyPatch().context() as mp:
        for k, v in mods.items():
            mp.setitem(sys.modules, k, v)
        with pytest.raises(RuntimeError, match="Secret is empty: my/secret"):
            require_secret("my/secret")


def test_exported_from_package() -> None:
    import wshtlib
    assert wshtlib.require_secret is require_secret
    assert "require_secret" in wshtlib.__all__
