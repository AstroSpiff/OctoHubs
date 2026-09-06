"""Environment helpers for OctoHubs settings."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Iterable


def env_first(keys: Iterable[str], default: str = "") -> str:
    for key in keys:
        value = os.environ.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return default


def octohubs_env(key: str, default: str = "") -> str:
    """Read one canonical OCTOHUBS_* environment variable."""
    return env_first((key,), default)


def octohubs_secret(key: str) -> str:
    """Read one canonical OCTOHUBS_* secret from its value or _FILE path."""
    file_path = env_first((f"{key}_FILE",))
    if file_path:
        try:
            value = Path(file_path).read_text(encoding="utf-8").strip()
        except OSError:
            value = ""
        if value:
            return value
    return env_first((key,))
