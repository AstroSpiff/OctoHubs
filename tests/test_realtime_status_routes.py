import asyncio
import json
import threading
import time
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import HTTPException
import pytest

from realtime.routes import emby_status_snapshot_api, init_realtime_routes
from realtime.status_snapshot import reset_status_snapshot_cache, shared_status_snapshot


@pytest.fixture(autouse=True)
def _reset_status_cache():
    reset_status_snapshot_cache()
    yield
    reset_status_snapshot_cache()


def test_status_snapshot_requires_authentication():
    def reject_auth(_request):
        raise HTTPException(status_code=401, detail="Autenticazione richiesta")

    init_realtime_routes(reject_auth)

    with patch("realtime.routes._build_emby_status_stream_payload") as snapshot:
        with pytest.raises(HTTPException, match="Autenticazione richiesta"):
            asyncio.run(emby_status_snapshot_api(SimpleNamespace()))

    snapshot.assert_not_called()


def test_status_snapshot_returns_the_same_payload_as_the_live_feed():
    init_realtime_routes(lambda _request: True)
    payload = {"success": True, "servers": {"green": {"status": {"ok": True}}}}

    with patch("realtime.routes._build_emby_status_stream_payload", return_value=payload):
        response = asyncio.run(emby_status_snapshot_api(SimpleNamespace()))

    assert response.status_code == 200
    assert response.media_type == "application/json"
    assert json.loads(response.body) == payload


def test_status_snapshot_get_reuses_the_live_feed_cache():
    init_realtime_routes(lambda _request: True)
    payload = {"success": True, "servers": {}}

    async def read_twice():
        return await asyncio.gather(
            emby_status_snapshot_api(SimpleNamespace()),
            emby_status_snapshot_api(SimpleNamespace()),
        )

    with patch(
        "realtime.routes._build_emby_status_stream_payload",
        return_value=payload,
    ) as snapshot:
        first, second = asyncio.run(read_twice())

    assert json.loads(first.body) == payload
    assert json.loads(second.body) == payload
    snapshot.assert_called_once_with()


def test_status_snapshot_cache_never_bypasses_authentication():
    payload = {"success": True, "servers": {}}
    init_realtime_routes(lambda _request: True)

    with patch("realtime.routes._build_emby_status_stream_payload", return_value=payload) as snapshot:
        asyncio.run(emby_status_snapshot_api(SimpleNamespace()))

        def reject_auth(_request):
            raise HTTPException(status_code=401, detail="Autenticazione richiesta")

        init_realtime_routes(reject_auth)
        with pytest.raises(HTTPException, match="Autenticazione richiesta"):
            asyncio.run(emby_status_snapshot_api(SimpleNamespace()))

    snapshot.assert_called_once_with()


@pytest.mark.anyio
async def test_shared_status_snapshot_is_single_flight_per_cache_key():
    calls = 0

    def build():
        nonlocal calls
        calls += 1
        time.sleep(0.05)
        return {"call": calls}

    results = await asyncio.gather(
        *(shared_status_snapshot(build, cache_key="single-flight") for _index in range(8))
    )

    assert calls == 1
    assert results == [{"call": 1}] * 8


@pytest.mark.anyio
async def test_cancelled_waiter_does_not_cancel_shared_snapshot_builder():
    calls = 0
    started = threading.Event()
    release = threading.Event()

    def build():
        nonlocal calls
        calls += 1
        started.set()
        release.wait(timeout=2)
        return {"call": calls}

    first = asyncio.create_task(
        shared_status_snapshot(build, cache_key="cancelled-waiter")
    )
    while not started.is_set():
        await asyncio.sleep(0)

    first.cancel()
    with pytest.raises(asyncio.CancelledError):
        await first

    second = asyncio.create_task(
        shared_status_snapshot(build, cache_key="cancelled-waiter")
    )
    await asyncio.sleep(0.02)
    assert calls == 1

    release.set()
    assert await second == {"call": 1}


def test_shared_status_snapshot_locks_are_safe_across_event_loops():
    def contend_once(value):
        started = threading.Event()
        release = threading.Event()

        def build():
            started.set()
            release.wait(timeout=2)
            return value

        async def read_twice():
            first = asyncio.create_task(
                shared_status_snapshot(build, cache_key="cross-loop")
            )
            while not started.is_set():
                await asyncio.sleep(0)
            second = asyncio.create_task(
                shared_status_snapshot(lambda: "unexpected", cache_key="cross-loop")
            )
            await asyncio.sleep(0)
            release.set()
            return await asyncio.gather(first, second)

        return asyncio.run(read_twice())

    assert contend_once("first") == ["first", "first"]
    from realtime.status_snapshot import invalidate_status_snapshot_cache

    invalidate_status_snapshot_cache("cross-loop")
    assert contend_once("second") == ["second", "second"]


@pytest.mark.anyio
async def test_invalidation_fences_an_in_flight_snapshot_publish():
    from realtime.status_snapshot import invalidate_status_snapshot_cache

    started = threading.Event()
    release = threading.Event()

    def old_builder():
        started.set()
        release.wait(timeout=2)
        return {"config": "old"}

    old_read = asyncio.create_task(
        shared_status_snapshot(old_builder, cache_key="generation-fence")
    )
    while not started.is_set():
        await asyncio.sleep(0)
    invalidate_status_snapshot_cache("generation-fence")
    release.set()

    assert await old_read == {"config": "old"}
    assert await shared_status_snapshot(
        lambda: {"config": "new"},
        cache_key="generation-fence",
    ) == {"config": "new"}
