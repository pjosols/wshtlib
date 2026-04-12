"""Tests for wshtlib.http"""

import pytest

from wshtlib.http import require_https_url


def test_valid_https_url() -> None:
    url = "https://example.com/path"
    assert require_https_url(url) == url


def test_rejects_http() -> None:
    with pytest.raises(ValueError, match="http://example.com"):
        require_https_url("http://example.com")


def test_rejects_ftp() -> None:
    with pytest.raises(ValueError):
        require_https_url("ftp://example.com/file")


def test_rejects_empty_string() -> None:
    with pytest.raises(ValueError):
        require_https_url("")


def test_rejects_no_hostname() -> None:
    with pytest.raises(ValueError):
        require_https_url("https:///path")
