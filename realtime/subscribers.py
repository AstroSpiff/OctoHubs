"""Thread-safe delivery to asyncio realtime subscribers."""

from __future__ import annotations

import asyncio
import threading
from typing import Any


class RealtimeSubscriber:
    """A bounded asyncio queue that can receive events from any thread."""

    def __init__(self, *, loop: asyncio.AbstractEventLoop, maxsize: int) -> None:
        self._loop = loop
        self._queue: asyncio.Queue[Any] = asyncio.Queue(maxsize=maxsize)
        self._active = True

    async def get(self, *, timeout: float) -> Any:
        """Wait for an event without consuming a worker from the default executor."""
        return await asyncio.wait_for(self._queue.get(), timeout=timeout)

    def publish(self, event: Any) -> bool:
        """Schedule one delivery on the subscriber loop from any calling thread."""
        if not self._active:
            return False
        try:
            self._loop.call_soon_threadsafe(self._enqueue, event)
        except RuntimeError:
            self._active = False
            return False
        return True

    def close(self) -> None:
        self._active = False

    def _enqueue(self, event: Any) -> None:
        if not self._active:
            return
        try:
            self._queue.put_nowait(event)
        except asyncio.QueueFull:
            # Keep the newest canonical signal. In particular, a terminal
            # success/error must not remain hidden behind stale progress events.
            try:
                self._queue.get_nowait()
            except asyncio.QueueEmpty:
                return
            try:
                self._queue.put_nowait(event)
            except asyncio.QueueFull:
                return


class RealtimeSubscriberRegistry:
    """Manage subscribers shared by async routes and threaded publishers."""

    def __init__(self) -> None:
        self._subscribers: list[RealtimeSubscriber] = []
        self._lock = threading.Lock()

    def subscribe(self, *, maxsize: int) -> RealtimeSubscriber:
        subscriber = RealtimeSubscriber(
            loop=asyncio.get_running_loop(),
            maxsize=maxsize,
        )
        with self._lock:
            self._subscribers.append(subscriber)
        return subscriber

    def unsubscribe(self, subscriber: RealtimeSubscriber) -> None:
        subscriber.close()
        with self._lock:
            if subscriber in self._subscribers:
                self._subscribers.remove(subscriber)

    def publish(self, event: Any) -> None:
        with self._lock:
            subscribers = tuple(self._subscribers)

        disconnected = [
            subscriber
            for subscriber in subscribers
            if not subscriber.publish(event)
        ]
        if not disconnected:
            return

        with self._lock:
            for subscriber in disconnected:
                if subscriber in self._subscribers:
                    self._subscribers.remove(subscriber)

    def close_all(self) -> None:
        """Deactivate and release every subscriber during application shutdown."""
        with self._lock:
            subscribers = tuple(self._subscribers)
            self._subscribers.clear()
        for subscriber in subscribers:
            subscriber.close()


sse_subscribers = RealtimeSubscriberRegistry()
websocket_subscribers = RealtimeSubscriberRegistry()
