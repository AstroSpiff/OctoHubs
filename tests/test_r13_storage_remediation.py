"""Regression tests for the thirteenth-pass storage/deployment remediations."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import hashlib
import os
from pathlib import Path
import subprocess
import threading

import pytest
from sqlalchemy import event
from sqlalchemy.exc import SQLAlchemyError

from core.storage import (
    DatabaseStorage,
    EmbyCollectionBackdrop,
    EmbyCollectionDefinition,
    EmbyCollectionPoster,
    StorageError,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _entrypoint_environment(config_dir: Path) -> dict[str, str]:
    environment = os.environ.copy()
    environment["PATH"] = f"{PROJECT_ROOT / 'venv' / 'bin'}:{environment.get('PATH', '')}"
    environment.update(
        {
            "OCTOHUBS_CONFIG_DIR": str(config_dir),
            "OCTOHUBS_DB_HOST": "database.example.test",
            "SECRET_KEY": "change-this-secret-key",
            "PASSWORD_SECRET": "",
        }
    )
    environment.pop("PASSWORD_SECRET_PREVIOUS", None)
    return environment


def test_concurrent_entrypoints_reuse_one_persisted_secret_pair(tmp_path):
    fingerprint_code = (
        "import hashlib,os; "
        "print('FINGERPRINT ' + hashlib.sha256(os.environ['SECRET_KEY'].encode()).hexdigest() + ' ' + "
        "hashlib.sha256(os.environ['PASSWORD_SECRET'].encode()).hexdigest())"
    )
    processes = [
        subprocess.Popen(
            [
                "sh",
                str(PROJECT_ROOT / "docker-entrypoint.sh"),
                "python",
                "-c",
                fingerprint_code,
            ],
            cwd=PROJECT_ROOT,
            env=_entrypoint_environment(tmp_path),
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        for _ in range(12)
    ]

    fingerprints: set[str] = set()
    for process in processes:
        stdout, stderr = process.communicate(timeout=20)
        assert process.returncode == 0, stderr or stdout
        fingerprint = next(line for line in stdout.splitlines() if line.startswith("FINGERPRINT "))
        fingerprints.add(fingerprint)

    assert len(fingerprints) == 1
    persisted = {
        key: value
        for key, value in (
            line.split("=", 1)
            for line in (tmp_path / ".env").read_text(encoding="utf-8").splitlines()
            if "=" in line and not line.lstrip().startswith("#")
        )
    }
    expected = "FINGERPRINT {} {}".format(
        hashlib.sha256(persisted["SECRET_KEY"].encode()).hexdigest(),
        hashlib.sha256(persisted["PASSWORD_SECRET"].encode()).hexdigest(),
    )
    assert fingerprints == {expected}


def test_first_interface_preferences_and_order_writes_share_one_lock(tmp_path):
    from core import auth

    previous_session = auth.db_session
    try:
        auth.init_auth(
            database_url=f"sqlite:///{tmp_path / 'r13-auth.db'}",
            allow_sqlite_for_tests=True,
        )
        user = auth.create_user("r13-user", "password-one")
        assert user is not None
        start = threading.Barrier(2)

        def save_preferences():
            start.wait(timeout=5)
            return auth.save_user_interface_preferences(
                user.id,
                {"primary_navigation": "sidebar", "secondary_navigation": "sidebar"},
            )

        def save_order():
            start.wait(timeout=5)
            return auth.save_user_interface_order(user.id, "research", ["requests", "rules"])

        with ThreadPoolExecutor(2) as executor:
            preferences = executor.submit(save_preferences)
            order = executor.submit(save_order)
            assert preferences.result(timeout=5) == {
                "primary_navigation": "sidebar",
                "secondary_navigation": "sidebar",
            }
            assert order.result(timeout=5) == ["requests", "rules"]

        assert auth.get_user_interface_preferences(user.id) == {
            "primary_navigation": "sidebar",
            "secondary_navigation": "sidebar",
        }
        assert auth.get_user_interface_order(user.id, "research") == ["requests", "rules"]
    finally:
        if auth.db_session is not None:
            auth.shutdown_auth()
        auth.db_session = previous_session


def test_collection_bundle_deletes_definition_and_images_in_one_storage_call(tmp_path):
    storage = DatabaseStorage({"URL": f"sqlite:///{tmp_path / 'r13-storage.db'}"})
    try:
        storage.ensure_ready()
        for model in (EmbyCollectionDefinition, EmbyCollectionPoster, EmbyCollectionBackdrop):
            model.__table__.create(storage._engine, checkfirst=True)
        storage.save_emby_collection_definition({"id": "collection-1", "name": "Collection"})
        storage.save_emby_collection_poster("collection-1", "image/jpeg", b"poster")
        storage.save_emby_collection_backdrop("collection-1", "image/jpeg", b"backdrop")

        storage.delete_emby_collection_bundle("collection-1")

        assert storage.get_emby_collection_definition("collection-1") is None
        assert storage.get_emby_collection_poster("collection-1") is None
        assert storage.get_emby_collection_backdrop("collection-1") is None
    finally:
        storage.close()


def test_collection_bundle_rolls_back_every_delete_on_failure(tmp_path):
    storage = DatabaseStorage({"URL": f"sqlite:///{tmp_path / 'r13-rollback.db'}"})
    storage.ensure_ready()
    for model in (EmbyCollectionDefinition, EmbyCollectionPoster, EmbyCollectionBackdrop):
        model.__table__.create(storage._engine, checkfirst=True)
    storage.save_emby_collection_definition({"id": "collection-1", "name": "Collection"})
    storage.save_emby_collection_poster("collection-1", "image/jpeg", b"poster")
    storage.save_emby_collection_backdrop("collection-1", "image/jpeg", b"backdrop")

    def fail_before_delete_flush(session, _flush_context, _instances):
        if any(isinstance(item, EmbyCollectionPoster) for item in session.deleted):
            raise SQLAlchemyError("injected bundle failure")

    event.listen(storage._Session.class_, "before_flush", fail_before_delete_flush)
    try:
        with pytest.raises(StorageError, match="bundle collezione"):
            storage.delete_emby_collection_bundle("collection-1")
    finally:
        event.remove(storage._Session.class_, "before_flush", fail_before_delete_flush)

    assert storage.get_emby_collection_definition("collection-1") is not None
    assert storage.get_emby_collection_poster("collection-1") is not None
    assert storage.get_emby_collection_backdrop("collection-1") is not None
    storage.close()


def test_start_dev_rejects_missing_external_database_credentials():
    environment = os.environ.copy()
    environment.update(
        {
            "SECRET_KEY": "session-secret-that-is-long-enough-for-tests",
            "PASSWORD_SECRET": "password-secret-that-is-long-enough-for-tests",
        }
    )
    for key in (
        "OCTOHUBS_DB_URL",
        "DATABASE_URL",
        "OCTOHUBS_DB_PASSWORD",
        "OCTOHUBS_DB_PASSWORD_FILE",
    ):
        environment.pop(key, None)

    result = subprocess.run(
        ["bash", str(PROJECT_ROOT / "start_dev.sh")],
        cwd=PROJECT_ROOT,
        env=environment,
        text=True,
        capture_output=True,
        check=False,
        timeout=10,
    )

    assert result.returncode != 0
    assert "External PostgreSQL credentials are required" in result.stdout
    assert "supersecret" not in (PROJECT_ROOT / "start_dev.sh").read_text(encoding="utf-8")
