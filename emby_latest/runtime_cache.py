"""Thread-safe bounded TTL cache for transient Latest API lookups."""

from __future__ import annotations

from collections import OrderedDict
from collections.abc import Iterator, MutableMapping
import threading
import time
from typing import Callable, Generic, TypeVar


K = TypeVar("K")
V = TypeVar("V")


class BoundedTTLCache(MutableMapping[K, V], Generic[K, V]):
    def __init__(
        self,
        *,
        max_entries: int,
        ttl_seconds: float,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.max_entries = max(1, int(max_entries))
        self.ttl_seconds = max(0.1, float(ttl_seconds))
        self._clock = clock
        self._values: OrderedDict[K, tuple[float, V]] = OrderedDict()
        self._lock = threading.RLock()

    def _purge_expired(self, now: float) -> None:
        expired = [key for key, (expires_at, _value) in self._values.items() if expires_at <= now]
        for key in expired:
            self._values.pop(key, None)

    def __getitem__(self, key: K) -> V:
        with self._lock:
            now = self._clock()
            self._purge_expired(now)
            expires_at, value = self._values[key]
            if expires_at <= now:
                self._values.pop(key, None)
                raise KeyError(key)
            self._values.move_to_end(key)
            return value

    def __setitem__(self, key: K, value: V) -> None:
        with self._lock:
            now = self._clock()
            self._purge_expired(now)
            self._values[key] = (now + self.ttl_seconds, value)
            self._values.move_to_end(key)
            while len(self._values) > self.max_entries:
                self._values.popitem(last=False)

    def __delitem__(self, key: K) -> None:
        with self._lock:
            del self._values[key]

    def __iter__(self) -> Iterator[K]:
        with self._lock:
            self._purge_expired(self._clock())
            return iter(tuple(self._values.keys()))

    def __len__(self) -> int:
        with self._lock:
            self._purge_expired(self._clock())
            return len(self._values)

    def clear(self) -> None:
        with self._lock:
            self._values.clear()
