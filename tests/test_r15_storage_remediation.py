"""Storage and migration regressions found during the fifteenth review pass."""

from __future__ import annotations

import json
import os
from uuid import uuid4

import pytest
from alembic import command
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import make_url


@pytest.fixture
def postgresql_schema_url():
    base_url = os.getenv("OCTOHUBS_TEST_POSTGRES_URL")
    if not base_url:
        if os.getenv("OCTOHUBS_REQUIRE_POSTGRES_TESTS") == "1":
            pytest.fail("OCTOHUBS_TEST_POSTGRES_URL is required")
        pytest.skip("set OCTOHUBS_TEST_POSTGRES_URL to run PostgreSQL tests")
    schema = f"octohubs_r15_{uuid4().hex}"
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


def test_download_credential_migration_scrubs_existing_search_history(tmp_path):
    from core.database_migrations import alembic_config

    database_url = f"sqlite:///{tmp_path / 'download-history.db'}"
    config = alembic_config(database_url)
    engine = create_engine(database_url, future=True)
    payload = {
        "items": [
            {
                "torrent": "https://indexer.example/download?apikey=secret&passkey=private",
                "guid": "magnet:?xt=urn:btih:abc&tr=https://tracker.example/private",
                "downloadUrl": "/api/download?apikey=relative-secret",
                "link": "ftp://account:ftp-secret@indexer.example/file.torrent",
                "infoUrl": "https://indexer.example/details?access_token=access-secret",
                "web": "https://indexer.example/details?apikey=secret",
                "title": "Safe title",
            }
        ]
    }
    with engine.begin() as connection:
        for table_name in ("scan_results", "manual_search_history"):
            connection.execute(
                text(
                    f"CREATE TABLE {table_name} ("
                    "id INTEGER PRIMARY KEY, generated_at DATETIME NOT NULL, payload JSON NOT NULL)"
                )
            )
            connection.execute(
                text(
                    f"INSERT INTO {table_name} (generated_at, payload) "
                    "VALUES (CURRENT_TIMESTAMP, :payload)"
                ),
                {"payload": json.dumps(payload)},
            )

    command.stamp(config, "20260901_13")

    command.upgrade(config, "head")

    with engine.connect() as connection:
        for table_name in ("scan_results", "manual_search_history"):
            stored = connection.execute(text(f"SELECT payload FROM {table_name}")).scalar_one()
            decoded = json.loads(stored) if isinstance(stored, str) else stored
            serialized = json.dumps(decoded)
            assert "secret" not in serialized
            assert "passkey" not in serialized
            assert "magnet:?" not in serialized
            assert "relative-secret" not in serialized
            assert "ftp-secret" not in serialized
            assert "access-secret" not in serialized
            assert decoded["items"][0]["title"] == "Safe title"
    engine.dispose()


def test_corrective_download_scrub_handles_databases_already_at_revision_14(tmp_path):
    from core.database_migrations import alembic_config

    database_url = f"sqlite:///{tmp_path / 'revision-14-download-history.db'}"
    config = alembic_config(database_url)
    engine = create_engine(database_url, future=True)
    with engine.begin() as connection:
        for table_name in ("scan_results", "manual_search_history"):
            connection.execute(
                text(
                    f"CREATE TABLE {table_name} ("
                    "id INTEGER PRIMARY KEY, generated_at DATETIME NOT NULL, payload JSON NOT NULL)"
                )
            )
            for index in range(510):
                payload = {
                    "items": [{
                        "torrent": f"/download?apikey=secret-{index}",
                        "infoUrl": f"https://indexer.example/item?access_token=secret-{index}",
                        "title": f"Safe title {index}",
                    }]
                }
                connection.execute(
                    text(
                        f"INSERT INTO {table_name} (generated_at, payload) "
                        "VALUES (CURRENT_TIMESTAMP, :payload)"
                    ),
                    {"payload": json.dumps(payload)},
                )

    command.stamp(config, "20260901_14")
    command.upgrade(config, "head")

    with engine.connect() as connection:
        for table_name in ("scan_results", "manual_search_history"):
            rows = connection.execute(
                text(f"SELECT payload FROM {table_name} ORDER BY id")
            ).scalars().all()
            assert len(rows) == 510
            assert all("secret-" not in str(payload) for payload in rows)
            assert "Safe title 509" in str(rows[-1])
    engine.dispose()


def test_head_repairs_database_already_stamped_with_non_cascading_asset_fk(
    postgresql_schema_url,
):
    from core.database_migrations import alembic_config, validate_migrations

    config = alembic_config(postgresql_schema_url)
    command.upgrade(config, "20260831_12")
    engine = create_engine(postgresql_schema_url, future=True)
    with engine.begin() as connection:
        connection.execute(
            text(
                "ALTER TABLE emby_collection_posters "
                "ADD CONSTRAINT fk_r15_wrong_asset "
                "FOREIGN KEY (collection_id) "
                "REFERENCES emby_collection_definitions(id)"
            )
        )
    command.stamp(config, "20260901_13")

    command.upgrade(config, "head")

    foreign_keys = inspect(engine).get_foreign_keys("emby_collection_posters")
    assert len(
        [
            foreign_key
            for foreign_key in foreign_keys
            if foreign_key.get("constrained_columns") == ["collection_id"]
        ]
    ) == 1
    assert foreign_keys[0]["referred_columns"] == ["id"]
    assert foreign_keys[0]["options"].get("ondelete") == "CASCADE"
    assert validate_migrations(postgresql_schema_url)["ok"] is True
    engine.dispose()


def test_postgresql_corrective_download_scrub_is_fail_closed_and_batched(
    postgresql_schema_url,
):
    from core.database_migrations import alembic_config

    config = alembic_config(postgresql_schema_url)
    engine = create_engine(postgresql_schema_url, future=True)
    with engine.begin() as connection:
        for table_name in ("scan_results", "manual_search_history"):
            connection.execute(
                text(
                    f"CREATE TABLE {table_name} ("
                    "id INTEGER GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY, "
                    "generated_at TIMESTAMPTZ NOT NULL, payload JSON NOT NULL)"
                )
            )
            for index in range(260):
                payload = {
                    "items": [{
                        "guid": f"urn:indexer:secret-{index}",
                        "web": f"https://indexer.example/item?password=secret-{index}",
                        "infoUrl": f"https://indexer.example/item?x-api-key=compound-{index}",
                        "title": f"Safe title {index}",
                    }]
                }
                connection.execute(
                    text(
                        f"INSERT INTO {table_name} (generated_at, payload) "
                        "VALUES (CURRENT_TIMESTAMP, CAST(:payload AS JSON))"
                    ),
                    {"payload": json.dumps(payload)},
                )

    command.stamp(config, "20260901_14")
    command.upgrade(config, "head")

    with engine.connect() as connection:
        for table_name in ("scan_results", "manual_search_history"):
            rows = connection.execute(
                text(f"SELECT payload FROM {table_name} ORDER BY id")
            ).scalars().all()
            assert len(rows) == 260
            assert all("secret-" not in json.dumps(payload) for payload in rows)
            assert all("compound-" not in json.dumps(payload) for payload in rows)
            assert rows[-1]["items"][0]["title"] == "Safe title 259"
    engine.dispose()
