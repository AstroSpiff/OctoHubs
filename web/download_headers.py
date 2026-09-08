"""Canonical response headers for downloadable application content."""

from __future__ import annotations

import os
from urllib.parse import quote
import unicodedata


_MAX_DOWNLOAD_FILENAME_CHARS = 180


def attachment_content_disposition(filename: object, *, fallback: str = "download") -> str:
    """Return an ASCII-only attachment header for an untrusted filename."""
    safe_name = _safe_download_filename(filename, fallback=fallback)
    ascii_name = unicodedata.normalize("NFKD", safe_name).encode("ascii", "ignore").decode("ascii")
    ascii_name = _safe_download_filename(ascii_name, fallback="download")
    encoded_name = quote(safe_name, safe="!#$&+-.^_`|~")
    return f"attachment; filename=\"{ascii_name}\"; filename*=UTF-8''{encoded_name}"


def _safe_download_filename(filename: object, *, fallback: str) -> str:
    def normalize(value: object) -> str:
        candidate = os.path.basename(str(value or "").replace("\\", "/"))
        candidate = "".join(
            "_" if ord(character) < 32 or ord(character) == 127 else character
            for character in candidate
        )
        candidate = candidate.replace('"', "_")[:_MAX_DOWNLOAD_FILENAME_CHARS]
        return "" if candidate in {".", ".."} else candidate

    return normalize(filename) or normalize(fallback) or "download"


__all__ = ["attachment_content_disposition"]
