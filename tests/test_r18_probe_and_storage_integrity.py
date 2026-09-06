"""Regression coverage for the R18 Probe and storage integrity fixes."""

from __future__ import annotations

import asyncio
from io import BytesIO
import json
import threading
import time
from types import SimpleNamespace

from alembic import command
from fastapi import UploadFile
import pytest
from sqlalchemy import create_engine, event, inspect, text
from sqlalchemy.orm import sessionmaker

from core.database_migrations import alembic_config
from core.storage import DatabaseStorage, StorageError
from core.storage.storage_models import (
    EmbyIconBinding,
    EmbyIconProfile,
    EmbyIconRule,
    EmbyProbeBlacklist,
    EmbyProbeHistory,
    EmbyProbeQueue,
    ManualSearchHistory,
)
from emby_probe.manager import EmbyProbeManager
from emby_probe.queue_leases import run_with_claim_renewal
from emby_users.icon_api_models import IconBindingRequest
from emby_users.icon_manager import IconManager
from emby_users.icon_routes import (
    api_emby_icons_binding_save,
    api_emby_icons_rule_save,
    init_emby_icon_routes,
)


def _storage_for(engine, database_url: str) -> DatabaseStorage:
    storage = DatabaseStorage({"URL": database_url})
    storage._engine = engine
    storage._Session = sessionmaker(bind=engine, expire_on_commit=False)
    return storage


def test_probe_result_commit_is_atomic_and_fenced_by_claim_token(tmp_path):
    database_url = f"sqlite:///{tmp_path / 'probe-result.db'}"
    engine = create_engine(database_url, future=True)
    for table in (EmbyProbeBlacklist, EmbyProbeQueue, EmbyProbeHistory):
        table.__table__.create(engine)
    storage = _storage_for(engine, database_url)
    storage.add_to_probe_queue(
        [{"server_id": "s1", "item_id": "i1", "scope": "libraries", "name": "Movie"}]
    )
    queue_id = storage.get_probe_queue("s1", scope="libraries")[0]["id"]
    first = storage.claim_probe_queue_items([queue_id])[0]
    history = {
        "server_id": "s1",
        "item_id": "i1",
        "scope": "libraries",
        "name": "Movie",
        "status": "ERROR",
        "error_details": "probe failed",
        "duration_ms": 4,
    }

    with storage._get_session() as session:
        entry = session.get(EmbyProbeQueue, queue_id)
        entry.claim_token = "replacement-owner"
        session.commit()

    assert storage.commit_probe_queue_result(
        queue_id,
        first["claim_token"],
        history,
        failure={"reason": "probe failed", "error_type": "ERROR"},
    ) is None
    assert storage.get_probe_history("s1", scope="libraries") == []
    assert storage.get_probe_blacklist("s1", scope="libraries") == []

    with storage._get_session() as session:
        entry = session.get(EmbyProbeQueue, queue_id)
        entry.claim_token = None
        entry.claimed_at = None
        session.commit()
    current = storage.claim_probe_queue_items([queue_id])[0]
    outcome = storage.commit_probe_queue_result(
        queue_id,
        current["claim_token"],
        history,
        failure={"reason": "probe failed", "error_type": "ERROR"},
    )

    assert outcome == {"retry_count": 1, "requeued": True}
    assert len(storage.get_probe_history("s1", scope="libraries")) == 1
    assert storage.get_probe_blacklist("s1", scope="libraries")[0]["retry_count"] == 1
    assert storage.get_probe_queue("s1", scope="libraries")[0]["claim_token"] is None
    storage.close()


def test_claim_renewal_does_not_return_with_a_live_renewal_thread():
    renewal_started = threading.Event()
    release_renewal = threading.Event()

    class Database:
        def renew_probe_queue_claim(self, _entry_id, _claim_token):
            renewal_started.set()
            assert release_renewal.wait(1)
            return True

    def callback():
        assert renewal_started.wait(1)
        threading.Timer(0.05, release_renewal.set).start()
        return "done"

    started_at = time.monotonic()
    assert run_with_claim_renewal(
        Database(),
        {"id": 1, "claim_token": "owner"},
        callback,
        interval_seconds=0.01,
    ) == "done"

    assert time.monotonic() - started_at >= 0.05
    assert not any(
        thread.name == "probe-lease-renewal" and thread.is_alive()
        for thread in threading.enumerate()
    )


def test_completed_claim_is_fenced_from_a_waiting_renewal():
    claim_finished = threading.Event()
    renewal_waiting = threading.Event()
    base_lock = threading.Lock()

    class CoordinatedLock:
        def __enter__(self):
            if threading.current_thread().name == "probe-lease-renewal":
                renewal_waiting.set()
            base_lock.acquire()
            return self

        def __exit__(self, *_args):
            base_lock.release()

    class Database:
        renewals = 0

        def renew_probe_queue_claim(self, _entry_id, _claim_token):
            self.renewals += 1
            return False

    database = Database()
    renew_lock = CoordinatedLock()

    def callback():
        with renew_lock:
            assert renewal_waiting.wait(1)
            claim_finished.set()
        return "committed"

    assert run_with_claim_renewal(
        database,
        {"id": 1, "claim_token": "owner"},
        callback,
        interval_seconds=0.01,
        claim_finished=claim_finished,
        renew_lock=renew_lock,
    ) == "committed"
    assert database.renewals == 0


def test_recent_probe_discards_result_when_claim_is_lost_during_atomic_commit():
    class Database:
        commit_calls: list[dict[str, object]] = []

        def renew_probe_queue_claim(self, _entry_id, _claim_token):
            return True

        def commit_probe_queue_result(
            self,
            _entry_id,
            _claim_token,
            history,
            **_kwargs,
        ):
            self.commit_calls.append(dict(history))
            # The storage contract returns None when the token no longer owns
            # the locked queue row; its transaction has made no mutations.
            return None

        def remove_from_probe_blacklist(self, *_args, **_kwargs):
            raise AssertionError("unfenced fallback mutation")

        def add_probe_history(self, *_args, **_kwargs):
            raise AssertionError("unfenced fallback mutation")

        def complete_probe_queue_claim(self, *_args, **_kwargs):
            raise AssertionError("split claim completion")

    manager = EmbyProbeManager()
    manager._probe_item = lambda *_args, **_kwargs: True
    manager._poll_recent_probe_metadata = lambda *_args, **_kwargs: (True, None)
    manager._update_status = lambda *_args, **_kwargs: None
    stopped = threading.Event()
    database = Database()

    result = manager._probe_claimed_recent_item(
        database,
        {"id": "server-1"},
        {
            "id": 7,
            "claim_token": "former-owner",
            "item_id": "item-1",
            "media_source_id": "source-1",
            "library_id": "library-1",
            "library_name": "Movies",
        },
        stopped,
        "recent",
        "recent_processing",
        "Movie",
    )

    assert result is None
    assert stopped.is_set()
    assert len(database.commit_calls) == 1
    assert database.commit_calls[0]["scope"] == "recent"


def test_probe_manager_shutdown_reports_blocked_claim_renewal_until_it_exits():
    renewal_started = threading.Event()
    release_renewal = threading.Event()
    stop_flag = threading.Event()

    class Database:
        def renew_probe_queue_claim(self, _entry_id, _claim_token):
            renewal_started.set()
            assert release_renewal.wait(1)
            return True

    def run_probe() -> None:
        run_with_claim_renewal(
            Database(),
            {"id": 1, "claim_token": "owner"},
            lambda: stop_flag.wait(1),
            interval_seconds=0.01,
        )

    manager = EmbyProbeManager()
    worker = threading.Thread(target=run_probe, daemon=True)
    manager._workers = {"server-1": {"recent_processing": worker}}
    manager._stop_flags = {"server-1": {"recent_processing": stop_flag}}
    worker.start()
    assert renewal_started.wait(1)

    assert manager.shutdown(0.01) is False
    assert worker.is_alive()

    release_renewal.set()
    assert manager.shutdown(1.0) is True
    assert not worker.is_alive()


def test_manual_search_keep_last_uses_one_snapshot_and_deterministic_order(tmp_path):
    database_url = f"sqlite:///{tmp_path / 'manual-history.db'}"
    engine = create_engine(database_url, future=True)
    ManualSearchHistory.__table__.create(engine)
    storage = _storage_for(engine, database_url)
    generated_at = "2026-09-02T12:00:00+00:00"
    for title in ("one", "two", "three"):
        storage.save_manual_search({"generated_at": generated_at, "title": title})

    statements: list[str] = []

    def capture_statement(_conn, _cursor, statement, _parameters, _context, _many):
        statements.append(statement)

    event.listen(engine, "before_cursor_execute", capture_statement)
    try:
        assert storage.delete_manual_searches(keep_last=1) == 2
    finally:
        event.remove(engine, "before_cursor_execute", capture_statement)

    delete_statements = [item for item in statements if item.lstrip().upper().startswith("DELETE")]
    assert len(delete_statements) == 1
    assert "SELECT" in delete_statements[0].upper()
    with storage._get_session() as session:
        remaining = session.query(ManualSearchHistory).one()
        assert remaining.payload["title"] == "three"
    storage.close()


def test_icon_profile_migration_removes_orphans_and_cascades(tmp_path):
    database_url = f"sqlite:///{tmp_path / 'icon-integrity.db'}"
    engine = create_engine(database_url, future=True)
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE emby_icon_profiles (id VARCHAR(36) PRIMARY KEY, label VARCHAR(255) NOT NULL, is_group_profile BOOLEAN)"))
        connection.execute(text("CREATE TABLE emby_icon_rules (profile_id VARCHAR(36) NOT NULL, column_key VARCHAR(100) NOT NULL, icon_path TEXT, PRIMARY KEY (profile_id, column_key))"))
        connection.execute(text("CREATE TABLE emby_icon_bindings (target_type VARCHAR(20) NOT NULL, target_id VARCHAR(255) NOT NULL, profile_id VARCHAR(36) NOT NULL, PRIMARY KEY (target_type, target_id))"))
        connection.execute(text("INSERT INTO emby_icon_profiles VALUES ('valid', 'Valid', 0)"))
        connection.execute(text("INSERT INTO emby_icon_rules VALUES ('valid', 'one', '/valid')"))
        connection.execute(text("INSERT INTO emby_icon_rules VALUES ('missing', 'two', '/orphan')"))
        connection.execute(text("INSERT INTO emby_icon_bindings VALUES ('user', 'one', 'valid')"))
        connection.execute(text("INSERT INTO emby_icon_bindings VALUES ('user', 'two', 'missing')"))
    command.stamp(alembic_config(database_url), "20260902_15")
    command.upgrade(alembic_config(database_url), "head")
    engine.dispose()
    engine = create_engine(database_url, future=True)

    for table_name in ("emby_icon_rules", "emby_icon_bindings"):
        foreign_keys = inspect(engine).get_foreign_keys(table_name)
        assert any(
            item["referred_table"] == "emby_icon_profiles"
            and (item.get("options") or {}).get("ondelete") == "CASCADE"
            for item in foreign_keys
        )
    with engine.begin() as connection:
        assert connection.execute(text("SELECT count(*) FROM emby_icon_rules WHERE profile_id='missing'")).scalar_one() == 0
        assert connection.execute(text("SELECT count(*) FROM emby_icon_bindings WHERE profile_id='missing'")).scalar_one() == 0
        connection.execute(text("PRAGMA foreign_keys=ON"))
        connection.execute(text("DELETE FROM emby_icon_profiles WHERE id='valid'"))
        assert connection.execute(text("SELECT count(*) FROM emby_icon_rules")).scalar_one() == 0
        assert connection.execute(text("SELECT count(*) FROM emby_icon_bindings")).scalar_one() == 0


def test_icon_storage_rejects_unknown_profiles(tmp_path):
    database_url = f"sqlite:///{tmp_path / 'icon-validation.db'}"
    engine = create_engine(database_url, future=True)
    for table in (EmbyIconProfile, EmbyIconRule, EmbyIconBinding):
        table.__table__.create(engine)
    storage = _storage_for(engine, database_url)

    with pytest.raises(StorageError, match="Icon profile not found"):
        storage.save_icon_rule("missing", "server", "/icon")
    with pytest.raises(StorageError, match="Icon profile not found"):
        storage.save_icon_binding("user", "server:user", "missing")
    storage.close()


def test_icon_service_rejects_unknown_profile_before_persistence():
    class Storage:
        saved = False

        def icon_profile_exists(self, _profile_id):
            return False

        def save_icon_binding(self, *_args):
            self.saved = True

    storage = Storage()
    manager = IconManager(
        storage,
        get_users_dashboard_data=lambda: {"groups": []},
        get_server_by_id=lambda _server_id: None,
    )

    with pytest.raises(ValueError, match="Icon profile not found"):
        manager.save_icon_binding("user", "server:user", "missing")
    assert storage.saved is False


def test_icon_binding_route_maps_a_stale_profile_to_not_found():
    manager = SimpleNamespace(
        icon_manager=SimpleNamespace(
            save_icon_binding=lambda *_args: (_ for _ in ()).throw(
                ValueError("Icon profile not found: missing")
            )
        )
    )
    init_emby_icon_routes(
        require_user=lambda _request: True,
        get_emby_user_manager=lambda: manager,
        validate_csrf=lambda _request, _token: True,
    )

    response = asyncio.run(
        api_emby_icons_binding_save(
            payload=IconBindingRequest(
                target_type="user",
                target_id="server:user",
                profile_id="missing",
            ),
            _csrf=None,
            user=True,
        )
    )

    assert response.status_code == 404
    assert json.loads(response.body) == {
        "ok": False,
        "error": "Icon profile not found",
    }


def test_icon_rule_route_maps_a_storage_race_to_not_found():
    manager = SimpleNamespace(
        icon_manager=SimpleNamespace(
            save_icon_rule=lambda *_args: (_ for _ in ()).throw(
                StorageError("Icon profile not found: missing")
            )
        )
    )
    init_emby_icon_routes(
        require_user=lambda _request: True,
        get_emby_user_manager=lambda: manager,
        validate_csrf=lambda _request, _token: True,
    )

    response = asyncio.run(
        api_emby_icons_rule_save(
            profile_id="missing",
            column_key="server",
            file=UploadFile(file=BytesIO(b"unused"), filename="icon.png"),
            _csrf=None,
            user=True,
        )
    )

    assert response.status_code == 404
    assert json.loads(response.body) == {
        "ok": False,
        "error": "Icon profile not found",
    }
