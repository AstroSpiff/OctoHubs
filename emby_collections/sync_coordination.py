"""Process-local serialization for collection definitions and Emby mutations."""

from __future__ import annotations

import copy
import threading
from functools import wraps
from typing import Any, Callable, Dict, TypeVar, cast


_COLLECTION_MUTATION_LOCK = threading.RLock()
_T = TypeVar("_T", bound=Callable)


def serialized_collection_mutation(func: _T) -> _T:
    @wraps(func)
    def guarded(*args, **kwargs):
        with _COLLECTION_MUTATION_LOCK:
            return func(*args, **kwargs)

    return cast(_T, guarded)


def mutate_stored_collection(
    backend: Any,
    definition_id: str,
    updater: Callable[[Dict[str, Any]], Dict[str, Any]],
) -> Dict[str, Any] | None:
    """Use the storage atomic mutation contract, with a test-backend fallback."""
    mutate = getattr(backend, "mutate_emby_collection_definition", None)
    if callable(mutate):
        return mutate(definition_id, updater)
    current = backend.get_emby_collection_definition(definition_id)
    if not isinstance(current, dict):
        return None
    updated = updater(copy.deepcopy(current))
    backend.save_emby_collection_definition(updated)
    return updated
