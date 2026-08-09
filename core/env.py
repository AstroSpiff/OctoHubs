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
    """Read the canonical OCTOHUBS_* env var with OCTOHUB_* legacy fallback."""
    legacy_key = key.replace("OCTOHUBS_", "OCTOHUB_", 1)
    return env_first((key, legacy_key), default)


def octohubs_secret(key: str) -> str:
    """Read a secret from OCTOHUBS_* or legacy OCTOHUB_* env/file variables."""
    legacy_key = key.replace("OCTOHUBS_", "OCTOHUB_", 1)
    for candidate in (key, legacy_key):
        file_path = env_first((f"{candidate}_FILE",))
        if file_path:
            try:
                value = Path(file_path).read_text(encoding="utf-8").strip()
            except OSError:
                value = ""
            if value:
                return value
        value = env_first((candidate,))
        if value:
            return value
    return ""
