"""Regression coverage for R14 storage integrity and bounded queue work."""

from __future__ import annotations

import multiprocessing
import os
from uuid import uuid4

import pytest
from alembic import command
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import make_url


def _collection_patch_worker(database_url, barrier, result_queue, field, value):
    from core.storage import DatabaseStorage

    storage = DatabaseStorage({"URL": database_url})
    try:
        barrier.wait(timeout=10)

        def update(current):
            current[field] = value
            return current

        result = storage.mutate_emby_collection_definition("collection-1", update)
        result_queue.put(result is not None)
    except Exception as exc:  # pragma: no cover - asserted in parent process
        result_queue.put(f"{type(exc).__name__}: {exc}")
    finally:
        storage.close()


@pytest.fixture
def postgresql_schema_url():
    base_url = os.getenv("OCTOHUBS_TEST_POSTGRES_URL")
    if not base_url:
        if os.getenv("OCTOHUBS_REQUIRE_POSTGRES_TESTS") == "1":
            pytest.fail("OCTOHUBS_TEST_POSTGRES_URL is required")
        pytest.skip("set OCTOHUBS_TEST_POSTGRES_URL to run PostgreSQL tests")
    schema = f"octohubs_r14_{uuid4().hex}"
    engine = create_engine(base_url, future=True)
    with engine.begin() as connection:
        connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    schema_url = make_url(base_url).update_query_dict(
        {"options": f"-csearch_path={schema}"}
    ).render_as_string(hide_password=False)
    try:
        yield schema_url
    finally:
        with engine.begin() as connection:
            connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        engine.dispose()


def test_collection_mutations_merge_across_postgresql_processes(postgresql_schema_url):
    from core.storage import DatabaseStorage

    storage = DatabaseStorage({"URL": postgresql_schema_url})
    storage.ensure_ready()
    storage.save_emby_collection_definition(
        {"id": "collection-1", "name": "Collection", "enabled": False}
    )
    context = multiprocessing.get_context("spawn")
    barrier = context.Barrier(2)
    result_queue = context.Queue()
    workers = [
        context.Process(
            target=_collection_patch_worker,
            args=(
                postgresql_schema_url,
                barrier,
                result_queue,
                field,
                value,
            ),
        )
        for field, value in (("enabled", True), ("last_sync_status", "success"))
    ]
    try:
        for worker in workers:
            worker.start()
        for worker in workers:
            worker.join(timeout=15)
        assert all(not worker.is_alive() for worker in workers)
        assert [result_queue.get(timeout=3) for _worker in workers] == [True, True]
        stored = storage.get_emby_collection_definition("collection-1")
        assert stored is not None
        assert stored["enabled"] is True
        assert stored["last_sync_status"] == "success"
    finally:
        for worker in workers:
            if worker.is_alive():
                worker.terminate()
                worker.join(timeout=3)
        storage.close()


def test_collection_asset_migration_prunes_orphans_and_cascades_postgresql(
    postgresql_schema_url,
):
    from core.database_migrations import alembic_config

    command.upgrade(alembic_config(postgresql_schema_url), "20260831_12")
    engine = create_engine(postgresql_schema_url, future=True)
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO emby_collection_posters "
                "(collection_id, mime_type, data) VALUES ('orphan', 'image/png', :data)"
            ),
            {"data": b"orphan"},
        )
        connection.execute(
            text(
                "INSERT INTO emby_collection_definitions (id, data) "
                "VALUES ('owned', CAST(:data AS JSON))"
            ),
            {"data": '{"id":"owned"}'},
        )
        connection.execute(
            text(
                "INSERT INTO emby_collection_posters "
                "(collection_id, mime_type, data) VALUES ('owned', 'image/png', :data)"
            ),
            {"data": b"owned"},
        )

    command.upgrade(alembic_config(postgresql_schema_url), "20260901_13")

    foreign_keys = inspect(engine).get_foreign_keys("emby_collection_posters")
    assert any(
        foreign_key["referred_table"] == "emby_collection_definitions"
        and foreign_key["options"].get("ondelete") == "CASCADE"
        for foreign_key in foreign_keys
    )
    with engine.begin() as connection:
        assert connection.execute(
            text("SELECT COUNT(*) FROM emby_collection_posters WHERE collection_id='orphan'")
        ).scalar_one() == 0
        connection.execute(
            text("DELETE FROM emby_collection_definitions WHERE id='owned'")
        )
        assert connection.execute(
            text("SELECT COUNT(*) FROM emby_collection_posters WHERE collection_id='owned'")
        ).scalar_one() == 0

    command.downgrade(alembic_config(postgresql_schema_url), "20260831_12")
    assert not inspect(engine).get_foreign_keys("emby_collection_posters")
    command.upgrade(alembic_config(postgresql_schema_url), "head")
    engine.dispose()


def test_collection_asset_save_rejects_missing_definition_sqlite(tmp_path):
    from core.storage import CollectionDefinitionNotFoundError, DatabaseStorage
    from core.storage.storage_models import (
        EmbyCollectionBackdrop,
        EmbyCollectionDefinition,
        EmbyCollectionPoster,
    )

    storage = DatabaseStorage({"URL": f"sqlite:///{tmp_path / 'assets.db'}"})
    try:
        storage.ensure_ready()
        for model in (
            EmbyCollectionDefinition,
            EmbyCollectionPoster,
            EmbyCollectionBackdrop,
        ):
            model.__table__.create(storage._engine, checkfirst=True)
        with pytest.raises(CollectionDefinitionNotFoundError):
            storage.save_emby_collection_poster("missing", "image/png", b"payload")
        assert storage.get_emby_collection_poster("missing") is None
    finally:
        storage.close()


def test_probe_claim_does_not_reload_the_complete_queue_sqlite(tmp_path, monkeypatch):
    from core.storage import DatabaseStorage
    from core.storage.storage_models import EmbyProbeQueue

    storage = DatabaseStorage({"URL": f"sqlite:///{tmp_path / 'probe.db'}"})
    try:
        storage.ensure_ready()
        EmbyProbeQueue.__table__.create(storage._engine, checkfirst=True)
        storage.add_to_probe_queue(
            [
                {"server_id": "server-1", "item_id": f"item-{index}", "scope": "recent"}
                for index in range(200)
            ]
        )
        first = storage.get_probe_queue("server-1", scope="recent", limit=1)[0]
        monkeypatch.setattr(
            storage,
            "get_probe_queue",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(
                AssertionError("claim must not reload the queue")
            ),
        )

        claimed = storage.claim_probe_queue_items([first["id"]])

        assert len(claimed) == 1
        assert claimed[0]["id"] == first["id"]
        assert claimed[0]["claim_token"]
    finally:
        storage.close()


def test_server_cleanup_prunes_collection_targets_without_deleting_draft_postgresql(
    postgresql_schema_url,
):
    from core.storage import DatabaseStorage

    storage = DatabaseStorage({"URL": postgresql_schema_url})
    try:
        storage.ensure_ready()
        storage.save_app_settings(
            {"EMBY": {"SERVERS": [{"id": "server-1"}, {"id": "server-2"}]}}
        )
        storage.save_emby_collection_definition(
            {
                "id": "multi",
                "server_id": "server-1",
                "server_ids": ["server-1", "server-2"],
                "delete_pending_servers": ["server-1", "server-2"],
                "enabled": True,
                "auto_enabled": True,
            }
        )
        storage.save_emby_collection_definition(
            {
                "id": "single",
                "server_id": "server-1",
                "server_ids": ["server-1"],
                "enabled": True,
                "auto_enabled": True,
            }
        )

        storage.remove_emby_server_data("server-1", remove_configuration=True)

        multi = storage.get_emby_collection_definition("multi")
        assert multi is not None
        assert multi["server_ids"] == ["server-2"]
        assert multi["server_id"] == "server-2"
        assert multi["delete_pending_servers"] == ["server-2"]
        assert multi["enabled"] is True
        assert multi["auto_enabled"] is True
        single = storage.get_emby_collection_definition("single")
        assert single is not None
        assert single["server_ids"] == []
        assert single["server_id"] == ""
        assert single["enabled"] is False
        assert single["auto_enabled"] is False
    finally:
        storage.close()
