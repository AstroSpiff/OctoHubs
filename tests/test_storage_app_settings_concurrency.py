"""Regression tests for concurrent application-settings updates."""

import threading

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from core.storage import AppSettings, DatabaseStorage, StorageError
from core.storage.storage_models import RequestRuleEntry
from emby_users.password_crypto import PasswordCipher


def test_concurrent_read_modify_write_preserves_independent_sections(tmp_path):
    database_url = f"sqlite:///{tmp_path / 'settings.db'}"
    engine = create_engine(database_url, future=True)
    AppSettings.__table__.create(engine)
    storage = DatabaseStorage({"URL": database_url})
    storage._engine = engine
    storage._Session = sessionmaker(bind=engine, expire_on_commit=False)
    storage.save_app_settings({"EVENT_BRIDGE": {"enabled": False}, "TELEGRAM": {"bots": []}})

    barrier = threading.Barrier(2)

    def update(section, value):
        snapshot = storage.load_app_settings()
        assert snapshot is not None
        barrier.wait(timeout=2)
        snapshot[section] = value
        storage.save_app_settings(snapshot)

    threads = [
        threading.Thread(target=update, args=("EVENT_BRIDGE", {"enabled": True})),
        threading.Thread(target=update, args=("TELEGRAM", {"bots": ["primary"]})),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=3)

    assert all(not thread.is_alive() for thread in threads)
    assert storage.load_app_settings() == {
        "EVENT_BRIDGE": {"enabled": True},
        "TELEGRAM": {"bots": ["primary"]},
    }
    engine.dispose()


def test_concurrent_read_modify_write_preserves_independent_nested_keys(tmp_path):
    database_url = f"sqlite:///{tmp_path / 'nested-settings.db'}"
    engine = create_engine(database_url, future=True)
    AppSettings.__table__.create(engine)
    storage = DatabaseStorage({"URL": database_url})
    storage._engine = engine
    storage._Session = sessionmaker(bind=engine, expire_on_commit=False)
    storage.save_app_settings(
        {"AUTO_TASKS": {"telegram": {"enabled": False}, "services": {"enabled": False}}}
    )

    telegram = storage.load_app_settings()
    services = storage.load_app_settings()
    assert telegram is not None
    assert services is not None
    telegram["AUTO_TASKS"]["telegram"]["enabled"] = True
    services["AUTO_TASKS"]["services"]["enabled"] = True

    storage.save_app_settings(telegram)
    storage.save_app_settings(services)

    assert storage.load_app_settings() == {
        "AUTO_TASKS": {"telegram": {"enabled": True}, "services": {"enabled": True}}
    }
    engine.dispose()


def test_seed_does_not_replace_a_value_written_after_the_seed_snapshot(tmp_path):
    database_url = f"sqlite:///{tmp_path / 'seed-settings.db'}"
    engine = create_engine(database_url, future=True)
    AppSettings.__table__.create(engine)
    storage = DatabaseStorage({"URL": database_url})
    storage._engine = engine
    storage._Session = sessionmaker(bind=engine, expire_on_commit=False)

    storage.update_app_settings_section(
        "AUTO_TASKS",
        lambda _current: {"job": {"enabled": True, "interval_minutes": 7}},
    )
    storage.seed_app_settings(
        {"AUTO_TASKS": {"job": {"enabled": False, "interval_minutes": 60}}},
    )

    assert storage.load_app_settings() == {
        "AUTO_TASKS": {"job": {"enabled": True, "interval_minutes": 7}},
    }
    engine.dispose()


def test_snapshot_merge_rejects_two_different_first_values_for_same_section(tmp_path):
    database_url = f"sqlite:///{tmp_path / 'settings-conflict.db'}"
    engine = create_engine(database_url, future=True)
    AppSettings.__table__.create(engine)
    storage = DatabaseStorage({"URL": database_url})
    storage._engine = engine
    storage._Session = sessionmaker(bind=engine, expire_on_commit=False)
    original = storage.load_app_settings() or {}
    storage.update_app_settings({"AUTO_TASKS": {"job": {"enabled": True}}})

    with pytest.raises(StorageError, match="Conflitto"):
        storage.save_app_settings_changes(
            original,
            {"AUTO_TASKS": {"job": {"enabled": False}}},
        )

    assert storage.load_app_settings() == {
        "AUTO_TASKS": {"job": {"enabled": True}},
    }
    engine.dispose()


def test_stale_snapshot_cannot_resurrect_a_deleted_section(tmp_path):
    database_url = f"sqlite:///{tmp_path / 'settings-delete-edit.db'}"
    engine = create_engine(database_url, future=True)
    AppSettings.__table__.create(engine)
    storage = DatabaseStorage(
        {"URL": database_url},
        app_settings_cipher=PasswordCipher(
            "test-app-settings-secret-with-enough-entropy"
        ),
    )
    storage._engine = engine
    storage._Session = sessionmaker(bind=engine, expire_on_commit=False)
    storage.save_app_settings({"KEEP": 1, "TRAKT": {"ACCESS_TOKEN": "old"}})
    stale = storage.load_app_settings()
    assert stale is not None

    storage.mutate_app_settings(
        lambda current: {key: value for key, value in current.items() if key != "TRAKT"}
    )
    stale["TRAKT"]["ACCESS_TOKEN"] = "new"
    with pytest.raises(StorageError, match="Conflitto"):
        storage.save_app_settings(stale)

    assert storage.load_app_settings() == {"KEEP": 1}
    engine.dispose()


def test_concurrent_request_rule_patches_preserve_distinct_request_ids(tmp_path):
    database_url = f"sqlite:///{tmp_path / 'request-rules.db'}"
    engine = create_engine(database_url, future=True)
    RequestRuleEntry.__table__.create(engine)
    storage = DatabaseStorage({"URL": database_url})
    storage._engine = engine
    storage._Session = sessionmaker(bind=engine, expire_on_commit=False)
    barrier = threading.Barrier(2)
    failures = []

    def update(request_id):
        try:
            barrier.wait(timeout=2)
            storage.patch_request_rules(
                {request_id: {"enabled": True, "query_terms": [request_id]}},
            )
        except BaseException as exc:  # pragma: no cover - asserted below
            failures.append(exc)

    threads = [
        threading.Thread(target=update, args=("request-0",)),
        threading.Thread(target=update, args=("request-1",)),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=3)

    assert failures == []
    assert set(storage.load_request_rules()) == {"request-0", "request-1"}
    engine.dispose()
