"""Eligibility rules shared by the Probe discovery workflows."""

from __future__ import annotations

from typing import Any


MEDIA_POLICY_STRM_ONLY = "strm_only"
MEDIA_POLICY_MISSING_MEDIAINFO = "missing_media_info"


def load_probe_config(storage: Any, server_id: str) -> dict[str, Any]:
    """Load the authoritative Probe configuration without fail-open defaults."""
    config = storage.get_probe_config(server_id)
    if not isinstance(config, dict):
        raise RuntimeError("Configurazione Probe non disponibile")
    return config


def normalize_media_policy(value: Any) -> str:
    """Return a supported Probe media policy, preserving the safe default."""
    if str(value or "").strip().lower() == MEDIA_POLICY_MISSING_MEDIAINFO:
        return MEDIA_POLICY_MISSING_MEDIAINFO
    return MEDIA_POLICY_STRM_ONLY


def is_probe_media_candidate(path: Any, policy: Any) -> bool:
    """Decide whether an Emby video item is eligible before metadata checks."""
    normalized_path = str(path or "").strip()
    if not normalized_path:
        return False
    if normalize_media_policy(policy) == MEDIA_POLICY_MISSING_MEDIAINFO:
        return True
    return normalized_path.lower().endswith(".strm")


__all__ = [
    "MEDIA_POLICY_MISSING_MEDIAINFO",
    "MEDIA_POLICY_STRM_ONLY",
    "is_probe_media_candidate",
    "load_probe_config",
    "normalize_media_policy",
]
