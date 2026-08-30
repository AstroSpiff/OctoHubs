"""Regression tests for concurrent application-settings updates."""

import threading

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from core.storage import AppSettings, DatabaseStorage


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
