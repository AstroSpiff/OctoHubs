"""Lock helpers for read-modify-write Transcode Guard history operations."""

from __future__ import annotations

from functools import wraps
import threading


_HISTORY_MUTATION_GUARD_KEY = "octohubs_transcode_guard:mutation_guard:v1"
_history_guard_state = threading.local()


def synchronized_history(method):
    @wraps(method)
    def guarded(self, *args, **kwargs):
        with self._lock:
            depth = int(getattr(_history_guard_state, "depth", 0))
            if depth > 0:
                return method(self, *args, **kwargs)

            storage = self._storage_provider()
            atomic_update = getattr(storage, "update_key_value", None)
            if not callable(atomic_update):
                return method(self, *args, **kwargs)

            result_holder = []

            def run_serialized(current):
                _history_guard_state.depth = depth + 1
                try:
                    result_holder.append(method(self, *args, **kwargs))
                finally:
                    _history_guard_state.depth = depth
                return current if current is not None else {"version": 1}

            atomic_update(_HISTORY_MUTATION_GUARD_KEY, run_serialized)
            return result_holder[0] if result_holder else None

    return guarded
