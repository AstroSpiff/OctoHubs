"""Compatibility shim for moved storage modules."""

from core.storage.storage_models import *  # noqa: F403

try:
    from core.storage.storage_models import __all__  # type: ignore
except Exception:  # pragma: no cover - compatibility fallback
    __all__ = []
