from __future__ import annotations

from core.storage.storage_probe import StorageProbeMixin
from emby_probe.media_policy import is_probe_media_candidate, normalize_media_policy
from emby_probe import snapshots


class _MemoryProbeConfig(StorageProbeMixin):
    def __init__(self, values=None):
        self.values = dict(values or {})

    def get_key_value(self, key):
        return self.values.get(key)

    def set_key_value(self, key, value):
        self.values[key] = value

    def delete_key(self, key):
        self.values.pop(key, None)


def test_probe_config_migrates_the_old_recent_key_once():
    storage = _MemoryProbeConfig(
        {"probe_recent_config:green": {"probe_parallelism": 3}}
    )

    config = storage.get_probe_config("green")

    assert config["probe_parallelism"] == 3
    assert config["media_policy"] == "strm_only"
    assert "probe_recent_config:green" not in storage.values
    assert storage.values["probe_config:green"] == {"probe_parallelism": 3}


def test_media_policy_defaults_to_strm_and_expands_to_video_items():
    assert normalize_media_policy("unexpected") == "strm_only"
    assert is_probe_media_candidate("/media/title.strm", "strm_only")
    assert not is_probe_media_candidate("/media/title.mkv", "strm_only")
    assert is_probe_media_candidate("/media/title.mkv", "missing_media_info")
    assert not is_probe_media_candidate("", "missing_media_info")


def test_probe_configuration_snapshot_persists_the_shared_media_policy(monkeypatch):
    class Backend:
        config = {}

        def get_probe_config(self, server_id):
            return self.config.get(server_id, {})

        def save_probe_config(self, server_id, config):
            self.config[server_id] = config

    backend = Backend()
    monkeypatch.setattr(
        snapshots,
        "_probe_load_config_servers",
        lambda: ({}, [{"id": "green", "enabled": True}], None),
    )
    monkeypatch.setattr(snapshots, "_ensure_db_backend", lambda: backend)

    saved, saved_status = snapshots._probe_config_save_snapshot(
        {
            "server_id": "green",
            "config": {"media_policy": "missing_media_info", "probe_parallelism": 3},
        }
    )
    loaded, loaded_status = snapshots._probe_config_get_snapshot("green")

    assert saved_status == 200
    assert saved["config"]["media_policy"] == "missing_media_info"
    assert loaded_status == 200
    assert loaded["config"]["probe_parallelism"] == 3
    assert loaded["config"]["media_policy"] == "missing_media_info"
