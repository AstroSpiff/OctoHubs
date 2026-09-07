"""Regression and invariant tests for encrypted application settings."""

from __future__ import annotations

import json

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from core.storage import AppSettings, DatabaseStorage, StorageError
from emby_users.password_crypto import PasswordCipher


CURRENT_SECRET = "r41-current-password-secret-with-enough-entropy"
PREVIOUS_SECRET = "r41-previous-password-secret-with-enough-entropy"


def _storage(tmp_path, name: str, cipher: PasswordCipher):
    database_url = f"sqlite:///{tmp_path / name}"
    engine = create_engine(database_url, future=True)
    AppSettings.__table__.create(engine)
    storage = DatabaseStorage({"URL": database_url}, app_settings_cipher=cipher)
    storage._engine = engine
    storage._Session = sessionmaker(bind=engine, expire_on_commit=False)
    return storage, engine


def _raw_settings(storage: DatabaseStorage) -> dict:
    session = storage._Session()
    try:
        row = session.get(AppSettings, 1)
        return json.loads(json.dumps(row.data)) if row is not None else {}
    finally:
        session.close()


def test_every_app_settings_credential_family_is_encrypted_at_rest(tmp_path):
    storage, engine = _storage(tmp_path, "all-secrets.db", PasswordCipher(CURRENT_SECRET))
    plaintext = {
        "JELLYSEERR_URL": "https://jellyseerr.example",
        "JELLYSEERR_API_KEY": "jellyseerr-canary",
        "OMDB_API_KEYS": ["omdb-one-canary", "omdb-two-canary"],
        "QBITTORRENT_PASSWORD": "qb-password-canary",
        "TRAKT": {
            "CLIENT_SECRET": "trakt-client-canary",
            "ACCESS_TOKEN": "trakt-access-canary",
            "REFRESH_TOKEN": "trakt-refresh-canary",
        },
        "EMBY": {
            "SERVERS": [
                {"id": "green", "url": "https://emby.example", "api_key": "emby-canary"}
            ]
        },
        "TELEGRAM": {"BOTS": [{"id": "bot", "token": "telegram-canary"}]},
        "DATABASE": {
            "PASSWORD": "database-canary",
            "URL": "postgresql://operator:url-canary@db.example/octohubs",
            "PARAMS": "sslmode=require&sslpassword=params-canary",
        },
        "EVENT_BRIDGE_CREDENTIALS": {"green": {"digest": "non-reusable-digest"}},
    }

    storage.save_app_settings(plaintext)

    serialized = json.dumps(_raw_settings(storage), sort_keys=True)
    for sentinel in (
        "jellyseerr-canary",
        "omdb-one-canary",
        "omdb-two-canary",
        "qb-password-canary",
        "trakt-client-canary",
        "trakt-access-canary",
        "trakt-refresh-canary",
        "emby-canary",
        "telegram-canary",
        "database-canary",
        "url-canary",
        "params-canary",
    ):
        assert sentinel not in serialized
    assert "https://jellyseerr.example" in serialized
    assert "non-reusable-digest" in serialized
    assert storage.load_app_settings() == plaintext
    engine.dispose()


def test_plaintext_migration_is_transactional_idempotent_and_transparent(tmp_path):
    storage, engine = _storage(tmp_path, "migration.db", PasswordCipher(CURRENT_SECRET))
    legacy = {
        "JELLYSEERR_API_KEY": "legacy-api-canary",
        "MDBLIST_API_KEYS": ["legacy-list-one", "legacy-list-two"],
        "EMBY": {"SERVERS": [{"id": "green", "api_key": "legacy-emby-canary"}]},
    }
    session = storage._Session()
    session.add(AppSettings(id=1, data=legacy))
    session.commit()
    session.close()

    assert storage.load_app_settings() == legacy
    migrated = _raw_settings(storage)
    assert "legacy-api-canary" not in json.dumps(migrated)
    assert "legacy-list-one" not in json.dumps(migrated)
    assert "legacy-emby-canary" not in json.dumps(migrated)

    assert storage.load_app_settings() == legacy
    assert _raw_settings(storage) == migrated
    engine.dispose()


def test_plaintext_migration_rolls_back_as_one_unit_when_commit_fails(tmp_path):
    storage, engine = _storage(tmp_path, "migration-rollback.db", PasswordCipher(CURRENT_SECRET))
    legacy = {
        "JACKETT_API_KEY": "legacy-jackett-canary",
        "EMBY": {"SERVERS": [{"id": "green", "api_key": "legacy-emby-canary"}]},
    }
    session = storage._Session()
    session.add(AppSettings(id=1, data=legacy))
    session.commit()
    session.close()
    regular_session_factory = storage._Session

    class _CommitFailureSession:
        def __init__(self):
            self._session = regular_session_factory()

        def __getattr__(self, name):
            return getattr(self._session, name)

        def commit(self):
            raise RuntimeError("commit canary")

    storage._Session = _CommitFailureSession
    with pytest.raises(RuntimeError, match="commit canary"):
        storage.load_app_settings()
    storage._Session = regular_session_factory

    assert _raw_settings(storage) == legacy
    engine.dispose()


def test_wrong_key_fails_closed_without_rewriting_ciphertext(tmp_path):
    storage, engine = _storage(tmp_path, "wrong-key.db", PasswordCipher(CURRENT_SECRET))
    storage.save_app_settings({"TMDB_API_KEY": "tmdb-canary"})
    persisted = _raw_settings(storage)
    storage._app_settings_cipher = PasswordCipher("different-password-secret-with-enough-entropy")

    with pytest.raises(StorageError, match="non decifrabili"):
        storage.load_app_settings()

    assert _raw_settings(storage) == persisted
    engine.dispose()


def test_load_config_propagates_wrong_app_settings_key(tmp_path, monkeypatch):
    from core import config_manager

    storage, engine = _storage(tmp_path, "wrong-key-startup.db", PasswordCipher(CURRENT_SECRET))
    storage.save_app_settings({"TMDB_API_KEY": "startup-canary"})
    persisted = _raw_settings(storage)
    storage._app_settings_cipher = PasswordCipher(
        "different-password-secret-with-enough-entropy"
    )
    monkeypatch.setenv("OCTOHUBS_DB_HOST", "database.example.internal")
    monkeypatch.setenv("OCTOHUBS_DB_PORT", "5432")
    monkeypatch.setenv("OCTOHUBS_DB_NAME", "octohubs")
    monkeypatch.setenv("OCTOHUBS_DB_USER", "octohubs")
    monkeypatch.setenv("OCTOHUBS_DB_PASSWORD", "test-only-password")
    monkeypatch.setattr(config_manager, "_get_db_backend", lambda _settings: storage)

    with pytest.raises(StorageError, match="non decifrabili"):
        config_manager.load_config()

    assert _raw_settings(storage) == persisted
    engine.dispose()


@pytest.mark.anyio
async def test_application_startup_stops_when_config_decryption_fails(monkeypatch):
    from runtime import app_setup
    from search import outbound_execution

    shutdown_calls = []
    monkeypatch.setattr(outbound_execution, "initialize_search_executor", lambda: None)
    monkeypatch.setattr(app_setup, "init_scheduler", lambda: None)
    monkeypatch.setattr(
        app_setup,
        "load_config",
        lambda: (_ for _ in ()).throw(StorageError("non decifrabili")),
    )

    async def shutdown():
        shutdown_calls.append(True)
        return True

    monkeypatch.setattr(app_setup, "shutdown_runtime_services", shutdown)

    with pytest.raises(StorageError, match="non decifrabili"):
        async with app_setup._application_lifespan(object()):
            pass

    assert shutdown_calls == [True]


def test_previous_key_envelopes_rotate_once_and_restore_with_current_key(tmp_path):
    storage, engine = _storage(tmp_path, "rotation.db", PasswordCipher(PREVIOUS_SECRET))
    value = {"TELEGRAM": {"BOTS": [{"token": "rotation-canary"}]}}
    storage.save_app_settings(value)
    previous_envelope = _raw_settings(storage)

    storage._app_settings_cipher = PasswordCipher(CURRENT_SECRET, PREVIOUS_SECRET)
    assert storage.load_app_settings() == value
    current_envelope = _raw_settings(storage)
    assert current_envelope != previous_envelope

    storage._app_settings_cipher = PasswordCipher(CURRENT_SECRET)
    assert storage.load_app_settings() == value
    assert _raw_settings(storage) == current_envelope
    engine.dispose()


def test_sensitive_write_without_persistent_key_fails_closed(tmp_path, monkeypatch):
    monkeypatch.delenv("PASSWORD_SECRET", raising=False)
    monkeypatch.delenv("PASSWORD_SECRET_PREVIOUS", raising=False)
    storage, engine = _storage(tmp_path, "missing-key.db", cipher=None)  # type: ignore[arg-type]

    with pytest.raises(StorageError, match="PASSWORD_SECRET non disponibile"):
        storage.save_app_settings({"JACKETT_API_KEY": "must-not-be-written"})

    assert _raw_settings(storage) == {}
    engine.dispose()
