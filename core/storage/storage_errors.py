"""Storage-specific exceptions."""

from __future__ import annotations


class StorageError(RuntimeError):
    """Raised when a storage backend cannot be used."""


class CollectionDefinitionNotFoundError(StorageError):
    """Raised when an asset mutation targets a missing collection definition."""
