"""Exit-code and error-reporting contracts for operator CLIs."""

from __future__ import annotations

from types import SimpleNamespace


def test_manage_users_returns_failure_when_create_fails(monkeypatch):
    from scripts import manage_users

    monkeypatch.setattr(manage_users, "_bootstrap_app", lambda: True)
    monkeypatch.setattr(manage_users, "create_user", lambda *_args: None)
    monkeypatch.setattr(manage_users, "_resolve_password", lambda _args: "unique-cli-password")

    result = manage_users.main(["create", "--username", "existing"])

    assert result == 1


def test_manage_users_returns_failure_for_missing_user(monkeypatch):
    from scripts import manage_users

    monkeypatch.setattr(manage_users, "_bootstrap_app", lambda: True)
    monkeypatch.setattr(manage_users, "get_user_by_username", lambda _username: None)

    assert manage_users.main(["set-role", "--username", "missing", "--role", "viewer"]) == 1


def test_manage_users_reports_bootstrap_failure_without_traceback(monkeypatch, capsys):
    from scripts import manage_users

    def fail_bootstrap():
        raise RuntimeError("database unavailable")

    monkeypatch.setattr(manage_users, "_bootstrap_app", fail_bootstrap)

    assert manage_users.main(["list"]) == 1
    captured = capsys.readouterr()
    assert "database unavailable" in captured.err
    assert "Traceback" not in captured.err


def test_database_cli_handles_migration_errors_without_traceback(monkeypatch, capsys):
    import core.storage
    from core.database_migrations import DatabaseMigrationError
    from cli import _handle_db_command

    class _Backend:
        def __init__(self, _settings):
            pass

        def get_migration_status(self):
            raise DatabaseMigrationError("revision registry invalid")

    monkeypatch.setattr(core.storage, "DatabaseStorage", _Backend)
    monkeypatch.setattr("cli._load_database_settings_for_cli", lambda: {"ENABLED": True})

    result = _handle_db_command(SimpleNamespace(db_command="status"))

    assert result == 1
    captured = capsys.readouterr()
    assert "revision registry invalid" in captured.err
    assert "Traceback" not in captured.err
