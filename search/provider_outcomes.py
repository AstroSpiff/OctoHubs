"""Typed outcomes for configured search indexers."""

from __future__ import annotations

from typing import Any, Iterable

import requests

from core.http_response_limits import read_complete_json_response

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


def load_provider_json(response: Any, *, provider: str) -> Any:
    """Decode the complete provider response without truncating result rows."""
    try:
        return read_complete_json_response(response, require_success=False)
    except requests.RequestException as exc:
        raise ProviderSearchError(f"Risposta JSON {provider} non valida") from exc
    except (RecursionError, TypeError, ValueError) as exc:
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


def provider_rows(rows: list[Any], *, provider: str) -> list[dict[str, Any]]:
    """Validate every provider row without applying a cardinality limit."""
    if any(not isinstance(row, dict) for row in rows):
        raise ProviderSearchError(f"Record non valido nella risposta {provider}")
    return list(rows)


def validate_provider_results(
    results: Any,
    *,
    provider: str,
) -> ProviderSearchResults:
    """Return the complete canonical provider result before declaring success."""
    if not isinstance(results, list):
        raise ProviderSearchError(f"Risultati {provider} non validi")
    rows = provider_rows(results, provider=provider)
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
        truncated=provider_results_truncated(results),
    )


def provider_results_truncated(results: Any) -> bool:
    return bool(getattr(results, "truncated", False))


__all__ = [
    "AggregatedSearchResults",
    "MAX_INDEXER_FIELD_CHARS",
    "ProviderSearchError",
    "ProviderSearchResults",
    "bounded_number",
    "provider_rows",
    "bounded_text",
    "load_provider_json",
    "provider_results_truncated",
    "validate_provider_results",
]
