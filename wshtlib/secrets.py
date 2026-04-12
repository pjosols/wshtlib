"""Secrets Manager helpers for Wholeshoot services."""

_cache: dict[str, str] = {}


def require_secret(name: str) -> str:
    """Return the value of a required Secrets Manager secret.

    name: Secret name or ARN.
    Returns the secret string value.
    Raises RuntimeError if the secret is absent or the value is empty.
    """
    if name in _cache:
        return _cache[name]
    import boto3
    from botocore.exceptions import ClientError

    try:
        response = boto3.client("secretsmanager").get_secret_value(SecretId=name)
    except ClientError as exc:
        raise RuntimeError(f"Secret not available: {name}") from exc
    value: str = response.get("SecretString", "")
    if not value:
        raise RuntimeError(f"Secret is empty: {name}")
    _cache[name] = value
    return value
