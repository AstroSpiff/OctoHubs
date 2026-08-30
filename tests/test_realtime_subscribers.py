import asyncio
import threading
from concurrent.futures import ThreadPoolExecutor

import pytest

from realtime.subscribers import RealtimeSubscriberRegistry


@pytest.mark.anyio
async def test_inactive_subscribers_do_not_consume_the_default_executor():
    loop = asyncio.get_running_loop()
    executor = ThreadPoolExecutor(max_workers=1)
    loop.set_default_executor(executor)
    worker_started = threading.Event()
    release_worker = threading.Event()

    def occupy_only_worker():
        worker_started.set()
        release_worker.wait(timeout=2)

    blocked_worker = loop.run_in_executor(None, occupy_only_worker)
    assert worker_started.wait(timeout=1)

    registry = RealtimeSubscriberRegistry()
    subscribers = [registry.subscribe(maxsize=1) for _ in range(8)]
    waiters = [subscriber.get(timeout=0.05) for subscriber in subscribers]

    try:
        results = await asyncio.wait_for(
            asyncio.gather(*waiters, return_exceptions=True),
            timeout=0.5,
        )
    finally:
        release_worker.set()
        await blocked_worker
        for subscriber in subscribers:
            registry.unsubscribe(subscriber)

    assert all(isinstance(result, asyncio.TimeoutError) for result in results)


@pytest.mark.anyio
async def test_threaded_publish_reaches_every_subscriber():
    registry = RealtimeSubscriberRegistry()
    subscribers = [registry.subscribe(maxsize=2) for _ in range(3)]
    event = {"MessageType": "LibraryChanged", "Data": {"server_id": "green"}}

    publisher = threading.Thread(target=registry.publish, args=(event,))
    publisher.start()
    publisher.join(timeout=1)

    try:
        assert publisher.is_alive() is False
        received = await asyncio.gather(
            *(subscriber.get(timeout=0.5) for subscriber in subscribers),
        )
        assert received == [event, event, event]
    finally:
        for subscriber in subscribers:
            registry.unsubscribe(subscriber)


@pytest.mark.anyio
async def test_slow_subscriber_drops_new_event_when_its_queue_is_full():
    registry = RealtimeSubscriberRegistry()
    subscriber = registry.subscribe(maxsize=1)

    try:
        registry.publish({"sequence": 1})
        await asyncio.sleep(0)
        registry.publish({"sequence": 2})
        await asyncio.sleep(0)

        assert await subscriber.get(timeout=0.5) == {"sequence": 1}
        with pytest.raises(asyncio.TimeoutError):
            await subscriber.get(timeout=0.01)
    finally:
        registry.unsubscribe(subscriber)
