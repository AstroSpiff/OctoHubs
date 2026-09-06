"""Local contracts for ninth-pass storage and deployment remediation."""

from __future__ import annotations

import ast
from pathlib import Path

from core.storage import DatabaseStorage
from core.storage.storage_models import AppSettings, JustWatchCache


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_historical_reconciliation_revisions_do_not_import_live_models():
    forbidden = {"core.auth", "core.storage.storage_models"}
    for name in (
        "20260829_03_reconcile_legacy_schema.py",
        "20260829_04_finalize_legacy_schema.py",
    ):
        path = PROJECT_ROOT / "alembic" / "versions" / name
        tree = ast.parse(path.read_text(encoding="utf-8"))
        imported = {
            node.module
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom) and node.module
        }
        assert imported.isdisjoint(forbidden)


def test_frozen_revision_metadata_matches_its_historical_contract():
    from core.database_baseline_20260829 import (
        REVISION_04_METADATA,
        REVISION_04_TABLE_COLUMNS,
    )

    assert set(REVISION_04_METADATA.tables) == set(REVISION_04_TABLE_COLUMNS)
    for table_name, columns in REVISION_04_TABLE_COLUMNS.items():
        assert tuple(REVISION_04_METADATA.tables[table_name].c.keys()) == columns


def test_app_settings_explicit_snapshot_merge_preserves_new_keys(tmp_path):
    storage = DatabaseStorage({"URL": f"sqlite:///{tmp_path / 'settings.db'}"})
    storage.ensure_ready()
    AppSettings.__table__.create(storage._engine, checkfirst=True)
    storage.save_app_settings({"BASE": 1})
    original = dict(storage.load_app_settings() or {})
    storage.update_app_settings({"CONCURRENT": 2})

    stored = storage.save_app_settings_changes(original, {**original, "SEED": 3})

    assert stored == {"BASE": 1, "CONCURRENT": 2, "SEED": 3}


def test_sqlite_justwatch_writes_use_upsert(tmp_path):
    storage = DatabaseStorage({"URL": f"sqlite:///{tmp_path / 'justwatch.db'}"})
    storage.ensure_ready()
    JustWatchCache.__table__.create(storage._engine, checkfirst=True)
    storage.save_justwatch_cache("Show", 1, 1, False, ["first"])
    storage.save_justwatch_cache("Show", 1, 1, True, None)

    cached = storage.get_justwatch_cache("Show", 1, 1)
    assert cached is not None
    assert cached["is_available"] is True
    assert cached["providers"] == ["first"]


def test_compose_forwards_documented_stream_refresh_default():
    compose = (PROJECT_ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    snapshots = (PROJECT_ROOT / "emby_runtime" / "snapshots.py").read_text(encoding="utf-8")

    assert "STREAMS_REFRESH_SECONDS=${STREAMS_REFRESH_SECONDS:-15}" in compose
    assert 'os.environ.get("STREAMS_REFRESH_SECONDS", "15")' in snapshots
