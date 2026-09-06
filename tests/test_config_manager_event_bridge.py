import threading
import time

import pytest


class _FakeBackend:
    def __init__(self, app_settings):
        self.app_settings = dict(app_settings)
        self.saved_app_settings = None

    def load_app_settings(self):
        return dict(self.app_settings)

    def save_app_settings(self, data):
        self.saved_app_settings = dict(data)
        self.app_settings = dict(data)

    def save_app_settings_changes(self, _original, data):
        self.save_app_settings(data)
        return dict(self.app_settings)

    def update_app_settings(self, updates):
        self.app_settings.update(updates)
        return dict(self.app_settings)

    def seed_app_settings(self, defaults):
        for key, value in defaults.items():
            self.app_settings.setdefault(key, value)
        self.saved_app_settings = dict(self.app_settings)
        return dict(self.app_settings)

    def load_request_rules(self):
        return {}

    def save_request_rules(self, _rules):
        pass


def _configure_external_database(monkeypatch):
    monkeypatch.setenv("OCTOHUBS_DB_HOST", "database.example.internal")
    monkeypatch.setenv("OCTOHUBS_DB_PORT", "5432")
    monkeypatch.setenv("OCTOHUBS_DB_NAME", "octohubs")
    monkeypatch.setenv("OCTOHUBS_DB_USER", "octohubs")
    monkeypatch.setenv("OCTOHUBS_DB_PASSWORD", "test-only-password")


def test_load_config_merges_event_bridge_app_settings(monkeypatch):
    from core import config_manager

    backend = _FakeBackend(
        {
            "EVENT_BRIDGE": {
                "SERVERS": {
                    "green": {
                        "WEBSOCKET_RECONNECT_SECONDS": 3,
                        "HTTP_TIMEOUT_SECONDS": 7,
                    }
                }
            }
        }
    )

    monkeypatch.setattr(config_manager, "_get_db_backend", lambda _settings: backend)
    monkeypatch.setattr(config_manager, "refresh_emby_user_manager_config", lambda _config: None)
    monkeypatch.setattr(config_manager, "_SYNC_AUTO_SCHEDULER", None)
    _configure_external_database(monkeypatch)

    config, is_valid = config_manager.load_config()

    assert is_valid is True
    assert config["EVENT_BRIDGE"]["DEFAULT"]["WEBSOCKET_RECONNECT_SECONDS"] == 5
    assert config["EVENT_BRIDGE"]["SERVERS"]["green"]["WEBSOCKET_RECONNECT_SECONDS"] == 3
    assert config["EVENT_BRIDGE"]["SERVERS"]["green"]["HTTP_TIMEOUT_SECONDS"] == 7


def test_load_config_ignores_config_json_file_settings(tmp_path, monkeypatch):
    from core import config_manager

    config_file = tmp_path / "config.json"
    config_file.write_text(
        '{"EVENT_BRIDGE":{"SERVERS":{"purple":{"WEBSOCKET_RECONNECT_SECONDS":4}}}}',
        encoding="utf-8",
    )
    backend = _FakeBackend({})

    monkeypatch.setenv("OCTOHUBS_CONFIG_FILE", str(config_file))
    monkeypatch.setattr(config_manager, "_get_db_backend", lambda _settings: backend)
    monkeypatch.setattr(config_manager, "refresh_emby_user_manager_config", lambda _config: None)
    monkeypatch.setattr(config_manager, "_SYNC_AUTO_SCHEDULER", None)
    _configure_external_database(monkeypatch)

    config, is_valid = config_manager.load_config()

    assert is_valid is True
    assert config["EVENT_BRIDGE"]["SERVERS"] == {}
    assert backend.saved_app_settings["EVENT_BRIDGE"]["SERVERS"] == {}


def test_concurrent_config_loads_publish_in_database_read_order(monkeypatch):
    from core import config_manager
    from emby_latest import manager as latest_manager

    first_started = threading.Event()
    release_first = threading.Event()

    class _OrderedBackend(_FakeBackend):
        def __init__(self):
            super().__init__({})
            self.calls = 0
            self.calls_lock = threading.Lock()

        def load_app_settings(self):
            with self.calls_lock:
                self.calls += 1
                call = self.calls
            if call == 1:
                first_started.set()
                release_first.wait(timeout=2)
            return {
                "AUTO_TASKS": {},
                "JELLYSEERR_URL": "old" if call == 1 else "new",
            }

    backend = _OrderedBackend()
    monkeypatch.setattr(config_manager, "_get_db_backend", lambda _settings: backend)
    monkeypatch.setattr(config_manager, "refresh_emby_user_manager_config", lambda _config: None)
    monkeypatch.setattr(config_manager, "_SYNC_AUTO_SCHEDULER", None)
    monkeypatch.setattr(latest_manager, "reconfigure_manager_if_initialized", lambda *_args: None)
    _configure_external_database(monkeypatch)
    results = []

    first = threading.Thread(target=lambda: results.append(config_manager.load_config()[0]["JELLYSEERR_URL"]))
    second = threading.Thread(target=lambda: results.append(config_manager.load_config()[0]["JELLYSEERR_URL"]))
    first.start()
    assert first_started.wait(timeout=1)
    second.start()
    time.sleep(0.03)
    assert backend.calls == 1

    release_first.set()
    first.join(timeout=2)
    second.join(timeout=2)

    assert results == ["old", "new"]
    assert config_manager._ACTIVE_CONFIG["JELLYSEERR_URL"] == "new"


def test_config_writer_waits_until_loader_has_published(monkeypatch):
    from core import config_manager
    from emby_latest import manager as latest_manager
    from services import app_settings

    read_started = threading.Event()
    release_read = threading.Event()
    writer_entered = threading.Event()

    class _BlockingBackend(_FakeBackend):
        def load_app_settings(self):
            snapshot = dict(self.app_settings)
            read_started.set()
            release_read.wait(timeout=2)
            return snapshot

        def update_app_settings(self, updates):
            writer_entered.set()
            return super().update_app_settings(updates)

    backend = _BlockingBackend({"AUTO_TASKS": {}, "JELLYSEERR_URL": "old"})
    monkeypatch.setattr(config_manager, "_get_db_backend", lambda _settings: backend)
    monkeypatch.setattr(config_manager, "refresh_emby_user_manager_config", lambda _config: None)
    monkeypatch.setattr(config_manager, "_SYNC_AUTO_SCHEDULER", None)
    monkeypatch.setattr(latest_manager, "reconfigure_manager_if_initialized", lambda *_args: None)
    monkeypatch.setattr(app_settings, "_ensure_db_backend", lambda: backend)
    _configure_external_database(monkeypatch)

    loader = threading.Thread(target=config_manager.load_config)
    writer = threading.Thread(
        target=lambda: app_settings._update_app_settings_overrides({"JELLYSEERR_URL": "new"})
    )
    loader.start()
    assert read_started.wait(timeout=1)
    writer.start()
    time.sleep(0.03)
    assert writer_entered.is_set() is False

    release_read.set()
    loader.join(timeout=2)
    writer.join(timeout=2)

    assert backend.app_settings["JELLYSEERR_URL"] == "new"
    assert config_manager._ACTIVE_CONFIG["JELLYSEERR_URL"] == "new"


def test_event_bridge_save_merges_latest_section_and_publishes_after_commit(monkeypatch):
    from core import config_manager
    from emby_runtime.event_bridge_configuration import _save_event_bridge_settings

    class _Backend:
        def update_app_settings_section(self, section, updater):
            assert section == "EVENT_BRIDGE"
            current = {
                "SERVERS": {
                    "green": {"ENABLED": False},
                    "blue": {"ENABLED": True},
                }
            }
            return {"EVENT_BRIDGE": updater(current)}

    monkeypatch.setattr(config_manager, "_ensure_db_backend", lambda: _Backend())
    monkeypatch.setattr(config_manager, "_ACTIVE_CONFIG", {"EVENT_BRIDGE": {}})

    persisted = _save_event_bridge_settings({"green": {"ENABLED": True}})

    assert persisted["SERVERS"]["green"]["ENABLED"] is True
    assert persisted["SERVERS"]["blue"]["ENABLED"] is True
    assert config_manager._ACTIVE_CONFIG["EVENT_BRIDGE"] == persisted


def test_event_bridge_save_does_not_publish_when_commit_fails(monkeypatch):
    from core import config_manager
    from core.storage import StorageError
    from emby_runtime.event_bridge_configuration import _save_event_bridge_settings

    class _Backend:
        def update_app_settings_section(self, _section, _updater):
            raise StorageError("commit failed")

    active = {"EVENT_BRIDGE": {"SERVERS": {"green": {"ENABLED": False}}}}
    monkeypatch.setattr(config_manager, "_ensure_db_backend", lambda: _Backend())
    monkeypatch.setattr(config_manager, "_ACTIVE_CONFIG", active)

    with pytest.raises(StorageError, match="commit failed"):
        _save_event_bridge_settings({"green": {"ENABLED": True}})

    assert active["EVENT_BRIDGE"]["SERVERS"]["green"]["ENABLED"] is False
