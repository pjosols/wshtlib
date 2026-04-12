"""Environment variable helpers — fail-fast with descriptive errors."""

import os


def require_env(name: str) -> str:
    """Return the value of a required environment variable.

    name: Variable name to look up.
    Returns the string value.
    Raises RuntimeError if the variable is absent or empty.
    """
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f"Required environment variable '{name}' is not set")
    return value
