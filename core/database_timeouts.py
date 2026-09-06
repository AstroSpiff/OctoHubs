"""Canonical PostgreSQL connection and statement deadlines."""

from __future__ import annotations

import os
from typing import Any

from sqlalchemy.engine import URL, make_url


DEFAULT_CONNECT_TIMEOUT_SECONDS = 5
DEFAULT_STATEMENT_TIMEOUT_MS = 30_000


def _bounded_int(name: str, default: int, *, minimum: int, maximum: int) -> int:
    try:
        value = int(str(os.environ.get(name, default)).strip())
    except (TypeError, ValueError):
        return default
    return min(maximum, max(minimum, value))


def postgres_engine_options(database_url: str | URL) -> dict[str, Any]:
    """Apply local deadlines unless the PostgreSQL URL already supplies them."""
    url = make_url(str(database_url)) if not isinstance(database_url, URL) else database_url
    if not url.drivername.startswith("postgresql"):
        return {}
    query = dict(url.query)
    connect_args: dict[str, Any] = {}
    if "connect_timeout" not in query:
        connect_args["connect_timeout"] = _bounded_int(
            "OCTOHUBS_DB_CONNECT_TIMEOUT_SECONDS",
            DEFAULT_CONNECT_TIMEOUT_SECONDS,
            minimum=1,
            maximum=60,
        )
    if "options" not in query:
        statement_timeout = _bounded_int(
            "OCTOHUBS_DB_STATEMENT_TIMEOUT_MS",
            DEFAULT_STATEMENT_TIMEOUT_MS,
            minimum=1_000,
            maximum=600_000,
        )
        connect_args["options"] = f"-c statement_timeout={statement_timeout}"
    return {"connect_args": connect_args} if connect_args else {}


__all__ = [
    "DEFAULT_CONNECT_TIMEOUT_SECONDS",
    "DEFAULT_STATEMENT_TIMEOUT_MS",
    "postgres_engine_options",
]
