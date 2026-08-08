"""AWS Secrets Manager helpers."""

import os
import time
from typing import Optional

# Secret name -> (monotonic deadline, value). Entries expire because a Lambda
# execution environment outlives a rotation: cached without a lifetime, a
# rotated-away secret keeps being served until the container is recycled, hours
# later, and the outage ends only by luck.
_cache: dict[str, tuple[float, str]] = {}

_DEFAULT_TTL_SECONDS = 300.0
_MAX_CACHE_ENTRIES = 128


def _ttl_seconds() -> float:
    """Return the configured cache lifetime in seconds.

    Read per call so it can be set after import. An unparseable value leaves
    the default in place rather than failing a secret read over a config typo.
    """
    raw = os.getenv("WSHT_SECRET_CACHE_TTL")
    if not raw:
        return _DEFAULT_TTL_SECONDS
    try:
        return max(0.0, float(raw))
    except ValueError:
        return _DEFAULT_TTL_SECONDS


def _cached(name: str, now: float) -> Optional[str]:
    """Return the live cached value for name, dropping it if it has expired.

    name: Secret name or ARN.
    now: Current ``time.monotonic()`` reading.
    """
    entry = _cache.get(name)
    if entry is None:
        return None
    expires_at, value = entry
    if expires_at <= now:
        del _cache[name]
        return None
    return value


def _store(name: str, value: str, now: float) -> None:
    """Cache a secret value until its TTL elapses.

    Expired entries are cleared before the size bound is applied, so a
    long-running process cannot be locked out of caching by 128 dead entries.

    name: Secret name or ARN.
    value: The fetched secret string.
    now: Current ``time.monotonic()`` reading.
    """
    ttl = _ttl_seconds()
    if ttl <= 0:
        return
    if len(_cache) >= _MAX_CACHE_ENTRIES:
        for expired in [key for key, (at, _) in _cache.items() if at <= now]:
            del _cache[expired]
    if name in _cache or len(_cache) < _MAX_CACHE_ENTRIES:
        _cache[name] = (now + ttl, value)


def clear_secret_cache() -> None:
    """Discard every cached secret, so the next read fetches afresh.

    Useful after a rotation you already know about, and in tests.
    """
    _cache.clear()


def require_secret(name: str) -> str:
    """Return the value of a required Secrets Manager secret.

    Values are cached for ``WSHT_SECRET_CACHE_TTL`` seconds (default 300).

    name: Secret name or ARN.
    Returns the secret string value.
    Raises RuntimeError if the secret is absent, empty, or holds binary data.
    """
    now = time.monotonic()
    cached = _cached(name, now)
    if cached is not None:
        return cached
    import boto3
    from botocore.exceptions import ClientError

    try:
        response = boto3.client("secretsmanager").get_secret_value(SecretId=name)
    except ClientError as exc:
        raise RuntimeError("Secret not available") from exc
    value = response.get("SecretString")
    if value:
        _store(name, str(value), now)
        return str(value)
    # Told apart from an empty secret: a binary secret is populated, and
    # reporting it as empty sends the operator looking for the wrong problem.
    if response.get("SecretBinary") is not None:
        raise RuntimeError("Secret holds binary data, which cannot be read as text")
    raise RuntimeError("Secret is empty")
