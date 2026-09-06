"""Typed, bounded outcomes for configured search indexers."""

from __future__ import annotations

from typing import Any, Iterable

import requests

from core.http_response_limits import read_bounded_json_response


MAX_INDEXER_RESPONSE_BYTES = 2 * 1024 * 1024
MAX_INDEXER_RESULTS = 500
MAX_AGGREGATED_SEARCH_RESULTS = 500
MAX_INDEXER_FIELD_CHARS = 4096


class ProviderSearchError(RuntimeError):
    """Raised when a configured provider cannot produce an authoritative result."""


class ProviderSearchResults(list[dict[str, Any]]):
    """A list-compatible provider result carrying an explicit truncation outcome."""

    def __init__(
        self,
        values: Iterable[dict[str, Any]] = (),
        *,
        provider: str,
        truncated: bool = False,
    ) -> None:
        super().__init__(values)
        self.provider = provider
        self.truncated = bool(truncated)


class AggregatedSearchResults(list[dict[str, Any]]):
    """List-compatible aggregate with partial/truncated provider diagnostics."""

    def __init__(
        self,
        values: Iterable[dict[str, Any]] = (),
        *,
        warnings: Iterable[str] = (),
        truncated: bool = False,
    ) -> None:
        super().__init__(values)
        self.warnings = list(warnings)
        self.truncated = bool(truncated)


def load_bounded_json(response: Any, *, provider: str) -> Any:
    """Decode a response only after enforcing a hard byte budget."""
    try:
        return read_bounded_json_response(
            response,
            max_bytes=MAX_INDEXER_RESPONSE_BYTES,
            require_success=False,
        )
    except requests.RequestException as exc:
        if "troppo grande" in str(exc):
            raise ProviderSearchError(
                f"Risposta {provider} oltre il limite consentito"
            ) from exc
        raise ProviderSearchError(f"Risposta JSON {provider} non valida") from exc


def bounded_text(
    value: Any,
    *,
    limit: int = MAX_INDEXER_FIELD_CHARS,
    provider: str = "Indexer",
    field: str = "testo",
    required: bool = False,
) -> str | None:
    """Return one bounded scalar string and reject malformed remote fields."""
    if value is None or value == "":
        if required:
            raise ProviderSearchError(f"Campo {field} mancante nella risposta {provider}")
        return None
    if not isinstance(value, str):
        raise ProviderSearchError(f"Campo {field} non valido nella risposta {provider}")
    bounded = value[:limit]
    if required and not bounded.strip():
        raise ProviderSearchError(f"Campo {field} mancante nella risposta {provider}")
    return bounded


def bounded_number(
    value: Any,
    *,
    provider: str,
    field: str,
    default: int = 0,
) -> int | float:
    """Accept only finite, non-negative numeric provider metadata."""
    if value is None or value == "":
        return default
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ProviderSearchError(f"Campo {field} non valido nella risposta {provider}")
    if value < 0 or value != value or value in (float("inf"), float("-inf")):
        raise ProviderSearchError(f"Campo {field} non valido nella risposta {provider}")
    return value


def bounded_provider_rows(rows: list[Any], *, provider: str) -> tuple[list[dict[str, Any]], bool]:
    """Return mapping rows within the provider cardinality budget."""
    truncated = len(rows) > MAX_INDEXER_RESULTS
    bounded = rows[:MAX_INDEXER_RESULTS]
    if any(not isinstance(row, dict) for row in bounded):
        raise ProviderSearchError(f"Record non valido nella risposta {provider}")
    return list(bounded), truncated


def validate_provider_results(
    results: Any,
    *,
    provider: str,
) -> ProviderSearchResults:
    """Return a bounded canonical provider result before declaring success."""
    if not isinstance(results, list):
        raise ProviderSearchError(f"Risultati {provider} non validi")
    rows, cardinality_truncated = bounded_provider_rows(results, provider=provider)
    validated: list[dict[str, Any]] = []
    for row in rows:
        canonical = dict(row)
        canonical["title"] = bounded_text(
            row.get("title"),
            limit=500,
            provider=provider,
            field="title",
            required=True,
        )
        for field in ("guid", "magnet", "magnetUri", "torrent", "downloadUrl", "web", "infoUrl"):
            canonical[field] = bounded_text(
                row.get(field), provider=provider, field=field
            )
        canonical["indexer"] = bounded_text(
            provider if row.get("indexer") in (None, "") else row.get("indexer"),
            limit=200,
            provider=provider,
            field="indexer",
            required=True,
        )
        canonical["seeders"] = bounded_number(
            row.get("seeders"), provider=provider, field="seeders"
        )
        canonical["size"] = bounded_number(
            row.get("size"), provider=provider, field="size"
        )
        validated.append(canonical)
    return ProviderSearchResults(
        validated,
        provider=provider,
        truncated=cardinality_truncated or provider_results_truncated(results),
    )


def provider_results_truncated(results: Any) -> bool:
    return bool(getattr(results, "truncated", False))


__all__ = [
    "AggregatedSearchResults",
    "MAX_INDEXER_FIELD_CHARS",
    "MAX_INDEXER_RESPONSE_BYTES",
    "MAX_INDEXER_RESULTS",
    "MAX_AGGREGATED_SEARCH_RESULTS",
    "ProviderSearchError",
    "ProviderSearchResults",
    "bounded_number",
    "bounded_provider_rows",
    "bounded_text",
    "load_bounded_json",
    "provider_results_truncated",
    "validate_provider_results",
]
