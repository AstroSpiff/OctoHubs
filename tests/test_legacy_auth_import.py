"""One-time migration coverage for the retired SQLite auth database."""

from __future__ import annotations

from sqlalchemy import create_engine


def test_legacy_auth_import_preserves_users_and_marks_the_source(tmp_path):
    from core import auth
    from core.database_migrations import upgrade_database
    from core.legacy_auth_import import import_legacy_auth_sqlite

    source_url = f"sqlite:///{tmp_path / 'auth.db'}"
    target_url = f"sqlite:///{tmp_path / 'octohubs.db'}"
    previous_session = auth.db_session
    try:
        auth.init_auth(database_url=source_url, allow_sqlite_for_tests=True)
        user = auth.create_user("legacy-admin", "legacy-password", role="admin")
        assert user is not None
        auth.db_session.remove()
        auth.db_session = previous_session

        upgrade_database(target_url)
        result = import_legacy_auth_sqlite(target_url, source_url)
        repeated = import_legacy_auth_sqlite(target_url, source_url)

        assert result["status"] == "imported"
        assert result["imported"]["users"] == 1
        assert repeated["status"] == "already_imported"

        engine = create_engine(target_url, future=True)
        try:
            with engine.connect() as connection:
                username = connection.execute(auth.User.__table__.select()).mappings().one()["username"]
                marker = connection.execute(auth.LegacyAuthImport.__table__.select()).mappings().one()
            assert username == "legacy-admin"
            assert marker["source_path"].endswith("auth.db")
        finally:
            engine.dispose()
    finally:
        if auth.db_session is not None:
            auth.db_session.remove()
        auth.db_session = previous_session
