"""Storage-specific exceptions."""

from __future__ import annotations


class StorageError(RuntimeError):
    """Raised when a storage backend cannot be used."""
