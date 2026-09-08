"""PostgreSQL regressions for the seventh storage/concurrency review."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
import multiprocessing
import os
from threading import Barrier, Event
from unittest.mock import patch
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url


@pytest.fixture
def postgresql_schema_url():
    base_url = os.getenv("OCTOHUBS_TEST_POSTGRES_URL")
    if not base_url:
        pytest.skip("set OCTOHUBS_TEST_POSTGRES_URL to run PostgreSQL concurrency tests")
    schema = f"octohubs_r7_{uuid4().hex}"
    engine = create_engine(base_url, future=True)
    with engine.begin() as connection:
        connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    url = make_url(base_url).update_query_dict(
        {"options": f"-csearch_path={schema}"}
    ).render_as_string(hide_password=False)
    try:
        yield url
    finally:
        with engine.begin() as connection:
            connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        engine.dispose()


def _storage(database_url):
    from core.storage import DatabaseStorage
    from emby_users.password_crypto import PasswordCipher

    storage = DatabaseStorage(
        {"URL": database_url},
        app_settings_cipher=PasswordCipher(
            "postgres-r7-settings-secret-with-enough-entropy"
        ),
    )
    storage.ensure_ready()
    return storage


def _claim_workflow_in_process(database_url, result_queue):
    """Act as an independent application worker after an advisory disconnect."""
    storage = _storage(database_url)
    lease = None
    try:
        lease = storage.acquire_workflow_lease()
        claimed = False
        if lease is not None:
            claimed = storage.try_start_workflow_execution(
                "workflow-replica",
                "full",
                {},
                "owner-replica",
                [("scan", 0)],
            )
        result_queue.put((lease is not None, claimed))
    finally:
        if lease is not None:
            storage.release_workflow_lease(lease)
        storage.close()


def test_server_cleanup_waits_for_latest_state_writer(postgresql_schema_url):
    from emby_latest import db_state

    writer = _storage(postgresql_schema_url)
    cleaner = _storage(postgresql_schema_url)
    writer.save_latest_state(
        {
            "server-a": {
                "movies": {"items": {"movie": {"item_id": "movie"}}},
                "series": {"items": {}},
            }
        }
    )
    loaded = Event()
    allow_save = Event()
    cleanup_done = Event()

    def update(state):
        loaded.set()
        assert allow_save.wait(10)
        state["server-a"]["movies"]["items"]["movie"]["notified"] = True
        return state

    def cleanup():
        cleaner.remove_emby_server_data("server-a")
        cleanup_done.set()

    with ThreadPoolExecutor(2) as executor:
        update_future = executor.submit(db_state.update_state, update, db_storage=writer)
        assert loaded.wait(10)
        cleanup_future = executor.submit(cleanup)
        assert cleanup_done.wait(0.25) is False
        allow_save.set()
        update_future.result(timeout=10)
        cleanup_future.result(timeout=10)

    assert "server-a" not in cleaner.load_latest_state()
    writer.close()
    cleaner.close()


def test_server_cleanup_rolls_back_every_phase_on_commit_failure(postgresql_schema_url):
    storage = _storage(postgresql_schema_url)
    storage.save_app_settings({
        "EMBY": {"SERVERS": [{"id": "server-a"}]},
        "EMBY_LATEST": {"STATE": {"server-a": {"seen": True}}},
    })
    storage.save_library_associations({("server-a", "library-a"): "Group"})

    with pytest.raises(Exception):
        storage.remove_emby_server_data(
            "server-a",
            remaining_servers=[{"id": "invalid", "payload": object()}],
        )

    assert storage.load_library_associations() == {
        ("server-a", "library-a"): "Group"
    }
    settings = storage.load_app_settings()
    assert settings is not None
    assert settings["EMBY"]["SERVERS"] == [{"id": "server-a"}]
    storage.close()


def test_stale_association_snapshot_cannot_restore_a_deleted_server(postgresql_schema_url):
    storage = _storage(postgresql_schema_url)
    storage.save_app_settings({"EMBY": {"SERVERS": [{"id": "server-a"}]}})
    stale = {("server-a", "library-a"): "Group"}
    storage.save_library_associations(stale)

    storage.remove_emby_server_data("server-a", remove_configuration=True)

    with pytest.raises(ValueError, match="server non configurati"):
        storage.save_library_associations(stale)
    assert storage.load_library_associations() == {}
    storage.close()


def test_server_cleanup_removes_probe_configuration(postgresql_schema_url):
    storage = _storage(postgresql_schema_url)
    storage.save_app_settings({"EMBY": {"SERVERS": [{"id": "server-a"}]}})
    storage.save_probe_config("server-a", {"window_size": 42})

    storage.remove_emby_server_data("server-a", remove_configuration=True)

    assert storage.get_key_value("probe_config:server-a") is None
    storage.close()


def test_server_cleanup_removes_pending_emby_user_creation_journal(
    postgresql_schema_url,
):
    storage = _storage(postgresql_schema_url)
    storage.save_app_settings({"EMBY": {"SERVERS": [{"id": "server-a"}]}})
    assert storage.reserve_emby_user_creation("server-a", "Alice") is True

    storage.remove_emby_server_data("server-a", remove_configuration=True)

    assert storage.get_emby_user_creation("server-a", "alice") is None
    storage.close()


def test_probe_writer_and_server_delete_share_one_transaction_fence(
    postgresql_schema_url,
):
    writer = _storage(postgresql_schema_url)
    cleaner = _storage(postgresql_schema_url)
    writer.save_app_settings({"EMBY": {"SERVERS": [{"id": "server-a"}]}})
    writer_session = writer._get_session()
    original_commit = writer_session.commit
    writer_ready = Event()
    allow_writer = Event()
    delete_done = Event()

    def delayed_commit():
        writer_ready.set()
        assert allow_writer.wait(10)
        original_commit()

    writer_session.commit = delayed_commit
    writer._get_session = lambda: writer_session

    with ThreadPoolExecutor(2) as executor:
        save_future = executor.submit(
            writer.save_probe_config_if_server_exists,
            "server-a",
            {"window_size": 99},
        )
        assert writer_ready.wait(10)
        delete_future = executor.submit(
            cleaner.remove_emby_server_data,
            "server-a",
            remove_configuration=True,
        )
        delete_future.add_done_callback(lambda _future: delete_done.set())
        assert delete_done.wait(0.25) is False
        allow_writer.set()
        assert save_future.result(timeout=10) is True
        delete_future.result(timeout=10)

    assert cleaner.get_key_value("probe_config:server-a") is None
    writer.close()
    cleaner.close()


def test_server_cleanup_removes_all_server_owned_unlinked_passwords(
    postgresql_schema_url,
):
    storage = _storage(postgresql_schema_url)
    storage.save_app_settings({
        "EMBY": {"SERVERS": [{"id": "server-a"}, {"id": "server-b"}]},
    })
    storage.save_group_password("unlinked_server-a_user-1", "secret-a")
    storage.save_group_password("unlinked_server-a_user-2", "secret-b")
    storage.save_group_password("unlinked_server-b_user-3", "secret-c")

    storage.remove_emby_server_data("server-a", remove_configuration=True)

    assert storage.get_group_password("unlinked_server-a_user-1") is None
    assert storage.get_group_password("unlinked_server-a_user-2") is None
    assert storage.get_group_password("unlinked_server-b_user-3") is not None
    storage.close()


def test_notification_dispatch_is_fenced_against_server_delete(
    postgresql_schema_url,
):
    from core.storage.storage_models import EmbyLatestNotificationDelivery
    from emby_latest.refresh_coordination import latest_refresh_guard

    sender = _storage(postgresql_schema_url)
    cleaner = _storage(postgresql_schema_url)
    sender.save_app_settings({"EMBY": {"SERVERS": [{"id": "server-a"}]}})
    claimed = Event()
    allow_provider_return = Event()
    cleanup_done = Event()

    def dispatch():
        with latest_refresh_guard(sender):
            assert sender.claim_latest_notification_delivery(
                delivery_key="a" * 64,
                server_id="server-a",
                publication_key="server-a:movie-1:batch-1",
                destination_key="bot-a:chat-a",
                claim_token="sender",
            ) == "acquired"
            claimed.set()
            assert allow_provider_return.wait(10)
            assert sender.complete_latest_notification_delivery(
                delivery_key="a" * 64,
                claim_token="sender",
            ) is True

    def cleanup():
        with latest_refresh_guard(cleaner):
            cleaner.remove_emby_server_data(
                "server-a",
                remove_configuration=True,
            )
        cleanup_done.set()

    with ThreadPoolExecutor(2) as executor:
        send_future = executor.submit(dispatch)
        assert claimed.wait(10)
        cleanup_future = executor.submit(cleanup)
        assert cleanup_done.wait(0.25) is False
        allow_provider_return.set()
        send_future.result(timeout=10)
        cleanup_future.result(timeout=10)

    session = cleaner._get_session()
    assert session.query(EmbyLatestNotificationDelivery).count() == 0
    session.close()
    assert sender.claim_latest_notification_delivery(
        delivery_key="b" * 64,
        server_id="server-a",
        publication_key="server-a:movie-2:batch-1",
        destination_key="bot-a:chat-a",
        claim_token="late-sender",
    ) == "server_deleted"
    sender.close()
    cleaner.close()


def test_stale_server_update_cannot_resurrect_deleted_server(postgresql_schema_url):
    from emby_runtime import server_routes

    storage = _storage(postgresql_schema_url)
    original = {
        "id": "server-a",
        "name": "Original",
        "url": "http://emby.invalid",
        "api_key": "secret",
        "enabled": True,
    }
    storage.save_app_settings({"EMBY": {"SERVERS": [original]}})
    status_started = Event()
    allow_status = Event()

    def delayed_status(_server):
        status_started.set()
        assert allow_status.wait(10)
        return {"ok": False}

    with patch("core.config_manager._ensure_db_backend", return_value=storage), patch.object(
        server_routes,
        "_ensure_db_backend",
        return_value=storage,
    ), patch.object(server_routes, "_fetch_emby_status", side_effect=delayed_status):
        with ThreadPoolExecutor(1) as executor:
            future = executor.submit(
                server_routes._save_server_values,
                {"name": "Changed", "url": original["url"], "api_key": "secret"},
                "server-a",
            )
            assert status_started.wait(10)
            removed = storage.remove_emby_server_data(
                "server-a",
                remove_configuration=True,
            )
            assert removed is not None
            assert removed["id"] == "server-a"
            allow_status.set()
            with pytest.raises(ValueError, match="Server non trovato"):
                future.result(timeout=10)

    settings = storage.load_app_settings()
    assert settings is not None
    assert settings["EMBY"]["SERVERS"] == []
    storage.close()


def test_complete_snapshot_writers_are_serialized(postgresql_schema_url):
    first = _storage(postgresql_schema_url)
    second = _storage(postgresql_schema_url)
    barrier = Barrier(2)
    left = {
        (f"a{index:035d}", f"l{index:035d}"): "left"
        for index in range(1500)
    }
    right = {
        (f"b{index:035d}", f"r{index:035d}"): "right"
        for index in range(1500)
    }

    def save(storage, payload):
        barrier.wait(timeout=10)
        storage.save_library_associations(payload)

    with ThreadPoolExecutor(2) as executor:
        futures = [
            executor.submit(save, first, left),
            executor.submit(save, second, right),
        ]
        for future in futures:
            future.result(timeout=20)

    stored = first.load_library_associations()
    assert len(stored) == 1500
    assert set(stored.values()) in ({"left"}, {"right"})
    first.close()
    second.close()


def test_workflow_lease_stop_and_reacquire_are_cross_storage(postgresql_schema_url):
    first = _storage(postgresql_schema_url)
    second = _storage(postgresql_schema_url)
    lease = first.acquire_workflow_lease()
    assert lease is not None
    assert first.try_start_workflow_execution(
        "workflow-a",
        "full",
        {},
        "owner-a",
        [("scan", 0)],
    ) is True
    assert second.acquire_workflow_lease() is None
    active = second.get_active_workflow_status()
    assert active is not None
    assert active["workflow_id"] == "workflow-a"
    assert second.request_active_workflow_stop("workflow-replaced") is False
    assert second.request_active_workflow_stop("workflow-a") is True
    assert first.workflow_stop_requested("workflow-a", "owner-a") is True
    assert first.finalize_workflow_execution(
        "workflow-a", "owner-a", "completed", "interrupted"
    ) is True
    first.release_workflow_lease(lease)

    replacement = second.acquire_workflow_lease()
    assert replacement is not None
    second.release_workflow_lease(replacement)
    first.close()
    second.close()


def test_workflow_managers_share_status_and_remote_stop(postgresql_schema_url):
    from core.tasks import WorkflowManager

    owner_storage = _storage(postgresql_schema_url)
    remote_storage = _storage(postgresql_schema_url)
    owner = WorkflowManager()
    remote = WorkflowManager()
    owner.set_db_storage(owner_storage)
    remote.set_db_storage(remote_storage)
    scan_started = Event()
    release_scan = Event()

    def trigger_scan(_context):
        scan_started.set()
        assert release_scan.wait(10)
        return True

    owner.set_callbacks(
        trigger_scan,
        lambda _context: False,
        lambda _context: True,
        lambda _context: True,
        lambda _context: None,
        lambda _context: None,
    )
    remote.set_callbacks(
        lambda _context: True,
        lambda _context: True,
        lambda _context: True,
        lambda _context: True,
        lambda _context: None,
        lambda _context: None,
    )

    assert owner.start("full") is True
    assert scan_started.wait(10)
    assert remote.start("full") is False
    remote_status = remote.get_status()
    assert remote_status["workflow_id"] == owner.get_status()["workflow_id"]
    assert remote_status["status"] == "running"
    remote.stop()
    release_scan.set()
    assert owner.wait(10) is True
    assert owner.get_status()["status"] == "completed"
    assert owner.get_status()["error"] == "Workflow interrotto dall'utente"
    owner_storage.close()
    remote_storage.close()


def test_workflow_recovery_and_retention(postgresql_schema_url):
    from core.storage.storage_models import WorkflowExecution, WorkflowStep, _utcnow

    storage = _storage(postgresql_schema_url)
    session = storage._get_session()
    old_time = _utcnow() - timedelta(days=60)
    session.add(WorkflowExecution(
        id="old-workflow",
        workflow_type="full",
        status="completed",
        started_at=old_time,
        completed_at=old_time,
    ))
    session.add(WorkflowStep(
        workflow_id="old-workflow",
        step_id="scan",
        step_index=0,
        status="done",
    ))
    session.add(WorkflowExecution(
        id="orphan-workflow",
        workflow_type="full",
        status="running",
        started_at=_utcnow(),
        owner_id="dead-owner",
        active_slot=1,
    ))
    session.commit()
    session.close()

    assert storage.recover_and_prune_workflows() == 1
    session = storage._get_session()
    assert session.get(WorkflowExecution, "old-workflow") is None
    recovered = session.get(WorkflowExecution, "orphan-workflow")
    assert recovered.status == "failed"
    assert recovered.active_slot is None
    assert session.query(WorkflowStep).filter_by(workflow_id="old-workflow").count() == 0
    session.close()
    storage.close()


def test_workflow_heartbeat_fences_replica_after_advisory_backend_termination(
    postgresql_schema_url,
):
    from core.storage.storage_models import WorkflowExecution
    from core.tasks import WorkflowManager

    owner_storage = _storage(postgresql_schema_url)
    owner = WorkflowManager()
    owner.set_db_storage(owner_storage)
    callback_started = Event()
    release_callback = Event()

    def blocked_scan(_context):
        callback_started.set()
        assert release_callback.wait(20)
        return True

    owner.set_callbacks(
        blocked_scan,
        lambda _context: True,
        lambda _context: True,
        lambda _context: True,
        lambda _context: None,
        lambda _context: None,
    )
    assert owner.start("full") is True
    assert callback_started.wait(10)
    lease = owner._workflow_lease
    assert lease is not None
    backend_pid = lease.connection.execute(text("SELECT pg_backend_pid()")).scalar_one()

    session = owner_storage._get_session()
    execution = session.query(WorkflowExecution).filter_by(active_slot=1).one()
    initial_heartbeat = execution.heartbeat_at
    session.close()
    assert Event().wait(2.5) is False
    session = owner_storage._get_session()
    execution = session.query(WorkflowExecution).filter_by(active_slot=1).one()
    assert execution.heartbeat_at > initial_heartbeat
    session.close()

    killer = create_engine(postgresql_schema_url, future=True)
    with killer.begin() as connection:
        assert connection.execute(
            text("SELECT pg_terminate_backend(:backend_pid)"),
            {"backend_pid": backend_pid},
        ).scalar_one() is True
    killer.dispose()

    process_context = multiprocessing.get_context("spawn")
    result_queue = process_context.Queue()
    replica = process_context.Process(
        target=_claim_workflow_in_process,
        args=(postgresql_schema_url, result_queue),
    )
    replica.start()
    replica.join(timeout=20)
    assert replica.exitcode == 0
    assert result_queue.get(timeout=2) == (True, False)

    release_callback.set()
    assert owner.wait(20) is True
    assert owner.get_status()["status"] == "completed"
    owner_storage.close()


def test_schema_validation_rejects_type_and_nullability_drift(postgresql_schema_url):
    from core.database_migrations import validate_migrations

    storage = _storage(postgresql_schema_url)
    storage.close()
    engine = create_engine(postgresql_schema_url, future=True)
    with engine.begin() as connection:
        connection.execute(text(
            "ALTER TABLE emby_latest_state_document "
            "ALTER COLUMN payload TYPE TEXT USING payload::text"
        ))
        connection.execute(text(
            "ALTER TABLE emby_latest_state_document "
            "ALTER COLUMN updated_at DROP NOT NULL"
        ))
    validation = validate_migrations(postgresql_schema_url)
    assert validation["ok"] is False
    assert any("column type mismatch" in error for error in validation["errors"])
    assert any("column nullability mismatch" in error for error in validation["errors"])
    engine.dispose()


def test_schema_validation_rejects_missing_workflow_active_slot_unique(
    postgresql_schema_url,
):
    from core.database_migrations import validate_migrations

    storage = _storage(postgresql_schema_url)
    storage.close()
    engine = create_engine(postgresql_schema_url, future=True)
    with engine.begin() as connection:
        connection.execute(text(
            "ALTER TABLE workflow_executions "
            "DROP CONSTRAINT uq_workflow_executions_active_slot"
        ))
    validation = validate_migrations(postgresql_schema_url)
    assert validation["ok"] is False
    assert any(
        "missing critical index on workflow_executions: (active_slot)" in error
        for error in validation["errors"]
    )
    engine.dispose()
