"""HTTP utilities — safe URL validation before outbound requests."""

from urllib.parse import urlparse


def require_https_url(url: str) -> str:
    """Validate that url uses https and has a non-empty hostname.

    url: The URL string to validate.
    Returns url unchanged if valid.
    Raises ValueError if the scheme is not https or hostname is empty.
    """
    parsed = urlparse(url)
    if parsed.scheme != "https" or not parsed.hostname:
        raise ValueError(f"Unsafe or invalid URL rejected: {url!r}")
    return url
