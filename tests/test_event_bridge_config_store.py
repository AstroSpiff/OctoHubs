"""Concurrency regressions for plugin-reported Event Bridge settings."""

from __future__ import annotations

import threading

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from core.storage import AppSettings, DatabaseStorage


def _storage(tmp_path) -> tuple[DatabaseStorage, object]:
    database_url = f"sqlite:///{tmp_path / 'event-bridge-settings.db'}"
    engine = create_engine(database_url, future=True)
    AppSettings.__table__.create(engine)
    storage = DatabaseStorage({"URL": database_url})
    storage._engine = engine
    storage._Session = sessionmaker(bind=engine, expire_on_commit=False)
    storage.save_app_settings(
        {
            "EMBY": {"SERVERS": [{"id": "green"}, {"id": "blue"}]},
            "EVENT_BRIDGE": {"DEFAULT": {"HTTP_TIMEOUT_SECONDS": 11}, "SERVERS": {}},
        }
    )
    return storage, engine


def test_concurrent_plugin_reports_preserve_settings_for_both_servers(tmp_path, monkeypatch):
    from core import config_manager
    from emby_runtime import event_bridge_config_store

    storage, engine = _storage(tmp_path)
    barrier = threading.Barrier(2)
    original_converter = event_bridge_config_store.event_bridge_settings_from_plugin_payload

    def convert_together(payload):
        settings = original_converter(payload)
        barrier.wait(timeout=2)
        return settings

    monkeypatch.setattr(config_manager, "_ACTIVE_CONFIG", {"EVENT_BRIDGE": {}})
    monkeypatch.setattr(config_manager, "_ensure_db_backend", lambda: storage)
    monkeypatch.setattr(
        event_bridge_config_store,
        "event_bridge_settings_from_plugin_payload",
        convert_together,
    )

    results: list[bool] = []

    def report(server_id: str, retry_count: int) -> None:
        results.append(
            event_bridge_config_store.apply_plugin_reported_settings(
                {
                    "server": {"id": server_id},
                    "event": {"type": "plugin.config_saved"},
                    "plugin": {"retryCount": retry_count},
                }
            )
        )

    threads = [
        threading.Thread(target=report, args=("green", 2)),
        threading.Thread(target=report, args=("blue", 4)),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=3)

    assert all(not thread.is_alive() for thread in threads)
    assert results == [True, True]
    persisted = storage.load_app_settings()
    assert persisted is not None
    assert persisted["EVENT_BRIDGE"]["DEFAULT"]["HTTP_TIMEOUT_SECONDS"] == 11
    assert persisted["EVENT_BRIDGE"]["SERVERS"]["green"]["RETRY_COUNT"] == 2
    assert persisted["EVENT_BRIDGE"]["SERVERS"]["blue"]["RETRY_COUNT"] == 4
    active_servers = config_manager._ACTIVE_CONFIG["EVENT_BRIDGE"]["SERVERS"]
    assert active_servers["green"]["RETRY_COUNT"] == 2
    assert active_servers["blue"]["RETRY_COUNT"] == 4
    engine.dispose()


def test_plugin_report_cannot_recreate_settings_for_a_removed_server(tmp_path, monkeypatch):
    from core import config_manager
    from emby_runtime import event_bridge_config_store

    storage, engine = _storage(tmp_path)
    settings = storage.load_app_settings()
    settings["EMBY"]["SERVERS"] = [{"id": "blue"}]
    storage.save_app_settings(settings)
    monkeypatch.setattr(config_manager, "_ACTIVE_CONFIG", {"EVENT_BRIDGE": {}})
    monkeypatch.setattr(config_manager, "_ensure_db_backend", lambda: storage)

    saved = event_bridge_config_store.apply_plugin_reported_settings(
        {
            "server": {"id": "green"},
            "event": {"type": "plugin.config_saved"},
            "plugin": {"retryCount": 3},
        }
    )

    assert saved is False
    persisted = storage.load_app_settings()
    assert "green" not in persisted["EVENT_BRIDGE"]["SERVERS"]
    engine.dispose()
