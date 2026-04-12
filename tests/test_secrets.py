"""Tests for wshtlib.secrets"""

from unittest.mock import MagicMock, patch

import pytest

import wshtlib.secrets as secrets_module
from wshtlib.secrets import require_secret


def setup_function() -> None:
    secrets_module._cache.clear()


def _make_client(secret_value: str) -> MagicMock:
    client = MagicMock()
    client.get_secret_value.return_value = {"SecretString": secret_value}
    return client


def test_returns_secret_value() -> None:
    client = _make_client("s3cr3t")
    with patch("boto3.client", return_value=client):
        assert require_secret("my/secret") == "s3cr3t"


def test_caches_value_on_second_call() -> None:
    client = _make_client("cached")
    with patch("boto3.client", return_value=client):
        require_secret("my/secret")
        require_secret("my/secret")
    client.get_secret_value.assert_called_once()


def test_different_names_fetched_separately() -> None:
    client = MagicMock()
    client.get_secret_value.side_effect = [
        {"SecretString": "val1"},
        {"SecretString": "val2"},
    ]
    with patch("boto3.client", return_value=client):
        assert require_secret("secret/a") == "val1"
        assert require_secret("secret/b") == "val2"
    assert client.get_secret_value.call_count == 2


def test_raises_runtime_error_when_empty() -> None:
    client = _make_client("")
    with patch("boto3.client", return_value=client):
        with pytest.raises(RuntimeError, match="my/secret"):
            require_secret("my/secret")


def test_raises_runtime_error_on_client_error() -> None:
    from botocore.exceptions import ClientError

    client = MagicMock()
    client.get_secret_value.side_effect = ClientError(
        {"Error": {"Code": "ResourceNotFoundException", "Message": "not found"}},
        "GetSecretValue",
    )
    with patch("boto3.client", return_value=client):
        with pytest.raises(RuntimeError, match="my/secret"):
            require_secret("my/secret")


def test_error_message_does_not_contain_secret_value() -> None:
    from botocore.exceptions import ClientError

    client = MagicMock()
    client.get_secret_value.side_effect = ClientError(
        {"Error": {"Code": "AccessDeniedException", "Message": "denied"}},
        "GetSecretValue",
    )
    with patch("boto3.client", return_value=client):
        with pytest.raises(RuntimeError) as exc_info:
            require_secret("my/secret")
    assert "denied" not in str(exc_info.value)


def test_exported_from_package() -> None:
    import wshtlib

    assert hasattr(wshtlib, "require_secret")
    assert "require_secret" in wshtlib.__all__
