import json


class _FakeBackend:
    def __init__(self, app_settings):
        self.app_settings = dict(app_settings)
        self.saved_app_settings = None

    def load_app_settings(self):
        return dict(self.app_settings)

    def save_app_settings(self, data):
        self.saved_app_settings = dict(data)
        self.app_settings = dict(data)

    def load_request_rules(self):
        return {}

    def save_request_rules(self, _rules):
        pass


def test_load_config_merges_event_bridge_app_settings(tmp_path, monkeypatch):
    from core import config_manager

    config_file = tmp_path / "config.json"
    config_file.write_text(
        json.dumps(
            {
                "DATABASE": {
                    "ENABLED": True,
                    "HOST": "localhost",
                    "PORT": "5432",
                    "NAME": "octohubs",
                    "USER": "octohubs",
                    "PASSWORD": "secret",
                    "DRIVER": "postgresql+psycopg2",
                }
            }
        ),
        encoding="utf-8",
    )
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

    monkeypatch.setattr(config_manager, "CONFIG_FILE", str(config_file))
    monkeypatch.setattr(config_manager, "_get_db_backend", lambda _settings: backend)
    monkeypatch.setattr(config_manager, "refresh_emby_user_manager_config", lambda _config: None)
    monkeypatch.setattr(config_manager, "_SYNC_AUTO_SCHEDULER", None)

    config, is_valid = config_manager.load_config()

    assert is_valid is True
    assert config["EVENT_BRIDGE"]["DEFAULT"]["WEBSOCKET_RECONNECT_SECONDS"] == 5
    assert config["EVENT_BRIDGE"]["SERVERS"]["green"]["WEBSOCKET_RECONNECT_SECONDS"] == 3
    assert config["EVENT_BRIDGE"]["SERVERS"]["green"]["HTTP_TIMEOUT_SECONDS"] == 7


def test_load_config_migrates_legacy_event_bridge_file_settings(tmp_path, monkeypatch):
    from core import config_manager

    config_file = tmp_path / "config.json"
    config_file.write_text(
        json.dumps(
            {
                "DATABASE": {
                    "ENABLED": True,
                    "HOST": "localhost",
                    "PORT": "5432",
                    "NAME": "octohubs",
                    "USER": "octohubs",
                    "PASSWORD": "secret",
                    "DRIVER": "postgresql+psycopg2",
                },
                "EVENT_BRIDGE": {
                    "SERVERS": {
                        "purple": {
                            "WEBSOCKET_RECONNECT_SECONDS": 4,
                        }
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    backend = _FakeBackend({})

    monkeypatch.setattr(config_manager, "CONFIG_FILE", str(config_file))
    monkeypatch.setattr(config_manager, "_get_db_backend", lambda _settings: backend)
    monkeypatch.setattr(config_manager, "refresh_emby_user_manager_config", lambda _config: None)
    monkeypatch.setattr(config_manager, "_SYNC_AUTO_SCHEDULER", None)

    config, is_valid = config_manager.load_config()

    assert is_valid is True
    assert config["EVENT_BRIDGE"]["SERVERS"]["purple"]["WEBSOCKET_RECONNECT_SECONDS"] == 4
    assert backend.saved_app_settings["EVENT_BRIDGE"]["SERVERS"]["purple"]["WEBSOCKET_RECONNECT_SECONDS"] == 4
