"""Search runtime state."""

from __future__ import annotations

from typing import Any

_active_search_sessions: dict[str, dict[str, Any]] = {}
