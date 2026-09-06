"""Validated first-frame contract for streaming search WebSockets."""

from __future__ import annotations

import asyncio
from typing import Any, Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, ValidationError, field_validator
from starlette.websockets import WebSocketDisconnect

from search.stream_limits import (
    MAX_SEARCH_FRAME_BYTES,
    MAX_SEARCH_INPUT_VARIANTS,
    MAX_SEARCH_QUERY_LENGTH,
    SEARCH_START_FRAME_TIMEOUT_SECONDS,
)
from search.rule_contracts import CustomSearchRulesInput


SearchQuery = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=MAX_SEARCH_QUERY_LENGTH),
]
SeasonNumber = Annotated[int, Field(ge=0, le=100)]


class SearchStreamStartPayload(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    action: Literal["start_search"]
    query_variants: list[SearchQuery] = Field(min_length=1, max_length=MAX_SEARCH_INPUT_VARIANTS)
    search_types: list[Literal["movie", "tv", "unknown"]] = Field(min_length=1, max_length=2)
    indexers: list[Literal["prowlarr", "jackett"]] = Field(min_length=1, max_length=2)
    use_jellyseerr_logic: bool = False
    use_custom_rules: bool = False
    tmdb_id: int | str | None = ""
    custom_rules: CustomSearchRulesInput | None = None
    seasons: list[SeasonNumber] = Field(default_factory=list, max_length=50)

    @field_validator("query_variants", "search_types", "indexers")
    @classmethod
    def reject_duplicates(cls, values: list[Any]) -> list[Any]:
        if len(values) != len(set(values)):
            raise ValueError("i valori duplicati non sono consentiti")
        return values

    @field_validator("tmdb_id")
    @classmethod
    def validate_tmdb_id(cls, value: int | str | None) -> int | str | None:
        if value in (None, ""):
            return value
        if isinstance(value, bool):
            raise ValueError("tmdb_id non valido")
        if isinstance(value, int):
            if value <= 0:
                raise ValueError("tmdb_id non valido")
            return value
        normalized = value.strip()
        if not normalized.isdigit() or len(normalized) > 12 or int(normalized) <= 0:
            raise ValueError("tmdb_id non valido")
        return normalized


class SearchStreamProtocolError(ValueError):
    """Safe validation error suitable for returning to a WebSocket client."""


async def receive_search_start(websocket: Any) -> SearchStreamStartPayload:
    try:
        message = await asyncio.wait_for(
            websocket.receive(),
            timeout=SEARCH_START_FRAME_TIMEOUT_SECONDS,
        )
    except TimeoutError as exc:
        raise SearchStreamProtocolError("Tempo scaduto in attesa dei parametri di ricerca") from exc

    if message.get("type") == "websocket.disconnect":
        raise WebSocketDisconnect(message.get("code", 1000))

    raw_text = message.get("text")
    raw_bytes = message.get("bytes")
    if raw_text is not None:
        encoded = raw_text.encode("utf-8")
    elif raw_bytes is not None:
        encoded = bytes(raw_bytes)
        try:
            raw_text = encoded.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise SearchStreamProtocolError("Frame di ricerca non valido") from exc
    else:
        raise SearchStreamProtocolError("Frame di ricerca mancante")

    if len(encoded) > MAX_SEARCH_FRAME_BYTES:
        raise SearchStreamProtocolError("Frame di ricerca troppo grande")

    try:
        return SearchStreamStartPayload.model_validate_json(raw_text)
    except ValidationError as exc:
        raise SearchStreamProtocolError("Parametri di ricerca non validi") from exc
