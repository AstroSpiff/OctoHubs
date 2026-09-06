"""Shared validation and safe diagnostics for outbound search queries."""

from __future__ import annotations

from typing import Any

from core.log_sanitization import sanitize_diagnostic_text
from search.stream_limits import MAX_SEARCH_QUERY_LENGTH


MAX_SEARCH_QUERY_LOG_LENGTH = 120


def normalize_bounded_search_query(value: Any) -> str | None:
    """Normalize a query and reject values outside the shared transport limit."""
    query = str(value or "").strip()
    if not query or len(query) > MAX_SEARCH_QUERY_LENGTH:
        return None
    return query


def search_query_for_log(value: Any) -> str:
    """Return useful query context without logging secrets or unbounded text."""
    return sanitize_diagnostic_text(value, max_length=MAX_SEARCH_QUERY_LOG_LENGTH)


__all__ = [
    "MAX_SEARCH_QUERY_LOG_LENGTH",
    "normalize_bounded_search_query",
    "search_query_for_log",
]
