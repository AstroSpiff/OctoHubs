"""Regression coverage for the one-time FastAPI password migration."""

from __future__ import annotations

import base64
import hashlib
from pathlib import Path

from cryptography.fernet import Fernet
from sqlalchemy import create_engine, text

from emby_users.password_crypto import (
    PasswordCipher,
    rotate_stored_password_ciphertexts,
)


def _legacy_ciphertext(secret: str, plaintext: str) -> str:
    digest = hashlib.sha256(secret.encode("utf-8")).digest()
    return Fernet(base64.urlsafe_b64encode(digest)).encrypt(
        plaintext.encode("utf-8")
    ).decode("ascii")


def test_password_retirement_migration_is_self_contained():
    source = (
        Path(__file__).resolve().parents[1]
        / "alembic/versions/20260908_23_retire_unversioned_emby_passwords.py"
    ).read_text(encoding="utf-8")

    assert 'down_revision = "20260908_22"' in source
    assert "substr(password_enc, 1, 3) <> 'v1:'" in source
    assert "from core." not in source


def test_upgrade_discards_only_unversioned_emby_passwords_and_unblocks_startup(
    tmp_path,
):
    from alembic import command

    from core.database_migrations import alembic_config
    from core.storage import DatabaseStorage

    database_url = f"sqlite:///{tmp_path / 'fastapi-password-upgrade.db'}"
    config = alembic_config(database_url)
    command.upgrade(config, "20260908_22")

    current_cipher = PasswordCipher("current-password-secret-that-is-long-enough")
    current_token = current_cipher.encrypt("current-password")
    legacy_token = _legacy_ciphertext(
        "legacy-fastapi-secret-that-is-long-enough",
        "legacy-password",
    )
    engine = create_engine(database_url, future=True)
    try:
        with engine.begin() as connection:
            connection.execute(
                text(
                    "CREATE TABLE emby_group_passwords ("
                    "group_id VARCHAR(266) PRIMARY KEY, "
                    "password_enc TEXT NOT NULL, updated_at DATETIME)"
                )
            )
            connection.execute(
                text(
                    "INSERT INTO emby_group_passwords (group_id, password_enc) "
                    "VALUES (:legacy_id, :legacy_token), "
                    "(:wrong_case_id, :wrong_case_token), "
                    "(:current_id, :current_token)"
                ),
                {
                    "legacy_id": "legacy-group",
                    "legacy_token": legacy_token,
                    "wrong_case_id": "wrong-case-group",
                    "wrong_case_token": "V1:not-accepted-by-the-runtime",
                    "current_id": "current-group",
                    "current_token": current_token,
                },
            )

        command.upgrade(config, "head")

        with engine.connect() as connection:
            rows = connection.execute(
                text(
                    "SELECT group_id, password_enc FROM emby_group_passwords "
                    "ORDER BY group_id"
                )
            ).all()
            assert connection.execute(
                text("SELECT version_num FROM alembic_version")
                ).scalar_one() == "20260908_24"
        assert rows == [("current-group", current_token)]

        storage = DatabaseStorage({"URL": database_url})
        try:
            assert rotate_stored_password_ciphertexts(storage, current_cipher) == 0
        finally:
            if storage._engine is not None:
                storage._engine.dispose()

        command.downgrade(config, "20260908_22")
        with engine.connect() as connection:
            assert connection.execute(
                text("SELECT group_id FROM emby_group_passwords")
            ).scalars().all() == ["current-group"]
    finally:
        engine.dispose()
