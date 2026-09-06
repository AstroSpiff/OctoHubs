"""Regression coverage for the twelfth review remediation."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import json

import pytest
from pydantic import ValidationError


def test_user_identifiers_reject_path_segments_before_calling_emby(monkeypatch):
    from emby_users import api_client_users
    from emby_users.api_models import ServerUserTarget

    outbound = []
    monkeypatch.setattr(
        api_client_users,
        "_call_emby_api",
        lambda *_args, **_kwargs: outbound.append((_args, _kwargs)),
    )

    for unsafe in ("../System/Info", "user/Policy", "%2FUsers", " user name "):
        with pytest.raises(ValidationError):
            ServerUserTarget(server_id="green", user_id=unsafe)
        assert api_client_users._fetch_emby_user_details({}, unsafe) == (
            None,
            "User ID mancante",
        )

    assert outbound == []


def test_user_batches_are_bounded_and_reject_duplicates():
    from emby_users.api_models import (
        BulkSettingsApplyRequest,
        CreateUsersRequest,
        LinkUsersRequest,
    )

    with pytest.raises(ValidationError):
        CreateUsersRequest(
            targets=[{"server_id": "green", "username": str(index)} for index in range(101)]
        )
    with pytest.raises(ValidationError):
        LinkUsersRequest(
            links=[
                {"server_id": "green", "user_id": "user-1"},
                {"server_id": "green", "user_id": "user-1"},
            ]
        )
    with pytest.raises(ValidationError):
        BulkSettingsApplyRequest(
            targets=[
                {"server_id": "green", "user_id": "user-1"},
                {"server_id": "green", "user_id": "user-1"},
            ],
            settings={},
        )


@pytest.mark.parametrize("payload", [[], "not-an-object", None])
def test_malformed_mdblist_payload_falls_back_without_aborting(monkeypatch, payload):
    from emby_latest import enrichment_sources

    class Response:
        status_code = 200
        headers = {}
        text = json.dumps(payload)

        def raise_for_status(self):
            return None

        def json(self):
            return payload

    monkeypatch.setattr(enrichment_sources.requests, "get", lambda *_args, **_kwargs: Response())

    assert enrichment_sources._fetch_mdblist_ratings_by_imdb(
        "tt-r12-malformed",
        ["key"],
        force_refresh=True,
    ) == {}


def test_invalid_mdblist_json_falls_back_without_aborting(monkeypatch):
    from emby_latest import enrichment_sources

    class Response:
        status_code = 200
        headers = {}
        text = "invalid"

        def raise_for_status(self):
            return None

        def json(self):
            raise ValueError("invalid JSON")

    monkeypatch.setattr(enrichment_sources.requests, "get", lambda *_args, **_kwargs: Response())

    assert enrichment_sources._fetch_mdblist_ratings_by_imdb(
        "tt-r12-invalid-json",
        ["key"],
        force_refresh=True,
    ) == {}


def test_request_cache_helpers_propagate_storage_failures(monkeypatch):
    from services import requests_cache

    class Backend:
        def load_request_overview(self):
            raise RuntimeError("read failed")

        def save_request_overview(self, _data):
            raise RuntimeError("write failed")

    monkeypatch.setattr(requests_cache, "_ensure_db_backend", lambda: Backend())

    with pytest.raises(RuntimeError, match="read failed"):
        requests_cache._load_cached_requests_overview()
    with pytest.raises(RuntimeError, match="write failed"):
        requests_cache._save_cached_requests_overview([])


def test_snapshot_first_writes_take_transaction_locks(tmp_path, monkeypatch):
    from core.storage import DatabaseStorage
    from core.storage import storage_collections, storage_requests
    from core.storage.storage_models import KeyValueEntry, RequestCacheEntry

    storage = DatabaseStorage({"URL": f"sqlite:///{tmp_path / 'r12-storage.db'}"})
    storage.ensure_ready()
    RequestCacheEntry.__table__.create(storage._engine, checkfirst=True)
    KeyValueEntry.__table__.create(storage._engine, checkfirst=True)
    locks = []
    monkeypatch.setattr(
        storage_requests,
        "lock_snapshot_writer",
        lambda _session, key: locks.append(key),
    )
    monkeypatch.setattr(
        storage_collections,
        "lock_snapshot_writer",
        lambda _session, key: locks.append(key),
    )

    storage.save_request_overview([{"id": 1}])
    storage.set_key_value("r12", {"saved": True})

    assert locks == ["request-overview", "key-value:r12"]
    assert storage.load_request_overview()[0] == [{"id": 1}]
    assert storage.get_key_value("r12") == {"saved": True}
    storage.close()


def test_concurrent_interface_orders_preserve_distinct_pages(tmp_path):
    from core import auth

    previous_session = auth.db_session
    try:
        auth.init_auth(
            database_url=f"sqlite:///{tmp_path / 'r12-auth.db'}",
            allow_sqlite_for_tests=True,
        )
        user = auth.create_user("r12-user", "password-one")
        assert user is not None

        with ThreadPoolExecutor(2) as executor:
            first = executor.submit(
                auth.save_user_interface_order,
                user.id,
                "research",
                ["requests", "rules"],
            )
            second = executor.submit(
                auth.save_user_interface_order,
                user.id,
                "emby",
                ["live", "users"],
            )
            assert first.result(timeout=5) == ["requests", "rules"]
            assert second.result(timeout=5) == ["live", "users"]

        assert auth.get_user_interface_order(user.id, "research") == ["requests", "rules"]
        assert auth.get_user_interface_order(user.id, "emby") == ["live", "users"]
    finally:
        if auth.db_session is not None:
            auth.shutdown_auth()
        auth.db_session = previous_session
