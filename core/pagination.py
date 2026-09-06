"""Shared hard limits for provider and Emby pagination loops."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from typing import Any, Sequence


MAX_PROVIDER_PAGES = 100
MAX_PROVIDER_ITEMS = 100_000
MAX_EMBY_PAGES = 10_000
MAX_EMBY_ITEMS = 2_000_000


class PaginationLimitError(RuntimeError):
    """Raised when a remote pagination contract stops making safe progress."""


def _page_fingerprint(items: Sequence[Any]) -> str:
    payload = json.dumps(list(items), sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


@dataclass
class PaginationGuard:
    """Bound pages/items and reject a non-empty page repeated consecutively."""

    max_pages: int
    max_items: int
    pages: int = 0
    items: int = 0
    _previous_fingerprint: str | None = None

    def observe(self, page_items: Sequence[Any]) -> None:
        next_pages = self.pages + 1
        next_items = self.items + len(page_items)
        if next_pages > self.max_pages or next_items > self.max_items:
            raise PaginationLimitError("Risposta paginata oltre i limiti applicativi")
        fingerprint = _page_fingerprint(page_items) if page_items else None
        if fingerprint is not None and fingerprint == self._previous_fingerprint:
            raise PaginationLimitError("Il provider ha restituito una pagina ripetuta")
        self.pages = next_pages
        self.items = next_items
        self._previous_fingerprint = fingerprint


def pagination_error(guard: PaginationGuard, page_items: Sequence[Any]) -> str | None:
    """Observe a page and project a pagination exception to an API error string."""
    try:
        guard.observe(page_items)
    except PaginationLimitError as exc:
        return str(exc)
    return None


__all__ = [
    "MAX_EMBY_ITEMS",
    "MAX_EMBY_PAGES",
    "MAX_PROVIDER_ITEMS",
    "MAX_PROVIDER_PAGES",
    "PaginationGuard",
    "PaginationLimitError",
    "pagination_error",
]
