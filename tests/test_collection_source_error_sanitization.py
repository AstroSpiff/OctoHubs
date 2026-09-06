"""Provider failures must not carry credentials into persistent UI state."""

from __future__ import annotations

import requests
import pytest
import logging


def test_mdblist_request_error_uses_a_stable_public_message(monkeypatch):
    from emby_collections.sources_mdblist import MdblistClient

    secret = "R5_MDBLIST_SECRET"

    def fail(url, **_kwargs):
        raise requests.ConnectionError(f"failed for {url}")

    monkeypatch.setattr(requests, "get", fail)

    with pytest.raises(RuntimeError) as raised:
        MdblistClient(secret).get_my_lists()

    assert secret not in str(raised.value)
    assert str(raised.value) == "Servizio MDBList temporaneamente non disponibile"


def test_tmdb_request_error_uses_a_stable_public_message(monkeypatch):
    from emby_collections import sources_tmdb

    secret = "R5_TMDB_SECRET"
    monkeypatch.setattr(sources_tmdb, "_get_tmdb_credentials", lambda: (secret, "it-IT"))

    def fail(_url, **_kwargs):
        raise requests.Timeout(f"https://api.themoviedb.org/3/list/1?api_key={secret}")

    monkeypatch.setattr(sources_tmdb.requests, "get", fail)

    with pytest.raises(RuntimeError) as raised:
        sources_tmdb._fetch_tmdb_payload(sources_tmdb.TMDB_LIST_ENDPOINT, "1")

    assert secret not in str(raised.value)
    assert str(raised.value) == "Servizio TMDB temporaneamente non disponibile"


def test_background_job_persists_a_generic_error_and_logs_a_redacted_traceback(monkeypatch, caplog):
    from services import background_jobs

    secret = "R5_BACKGROUND_SECRET"
    failed = []

    class Tracker:
        def start(self, *_args, **_kwargs):
            return {"id": "operation-r5"}

        def update(self, *_args, **_kwargs):
            return None

        def finish(self, *_args, **_kwargs):
            return None

        def fail(self, _operation_id, message):
            failed.append(message)

    class StopEvent:
        def is_set(self):
            return False

    monkeypatch.setattr(background_jobs, "background_job_registry", type("Registry", (), {
        "start": staticmethod(lambda _key, create, target: (create(), (target(StopEvent()) is None))),
    })())
    monkeypatch.setattr("app_state.get_operation_tracker", lambda: Tracker())

    def fail(_context):
        raise RuntimeError(f"failed https://example.test/?apikey={secret}")

    background_jobs.start_tracked_background_job(
        kind="test",
        title="Test",
        work=fail,
    )

    assert failed == [background_jobs._GENERIC_FAILURE_MESSAGE]
    assert secret not in caplog.text


@pytest.mark.anyio
async def test_collection_route_never_returns_storage_credentials(monkeypatch, caplog):
    from core.storage import StorageError
    from emby_collections import routes

    secret = "R6_CANARY_DB_PASSWORD"
    monkeypatch.setattr(routes, "_logger", logging.getLogger("test.collections"))
    monkeypatch.setattr(
        routes,
        "list_collection_definitions",
        lambda: (_ for _ in ()).throw(
            StorageError(f"failed postgresql://admin:{secret}@db/octohubs")
        ),
    )

    response = await routes.api_emby_collections_list(user={"username": "viewer"})

    assert response.status_code == 500
    assert secret not in response.body.decode()
    assert secret not in caplog.text
