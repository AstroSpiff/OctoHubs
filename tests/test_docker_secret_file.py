"""Contracts for the optional Docker Compose database-password secret."""

from pathlib import Path

from core.env import octohubs_secret


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_compose_secret_is_mounted_only_in_the_application():
    override = (PROJECT_ROOT / "docker-compose.secrets.yml").read_text(
        encoding="utf-8"
    )

    assert 'OCTOHUBS_DB_PASSWORD: ""' in override
    assert "OCTOHUBS_DB_PASSWORD_FILE: /run/secrets/octohubs_db_password" in override
    assert "POSTGRES_PASSWORD" not in override
    assert override.count("- octohubs_db_password") == 1
    assert "file: ${OCTOHUBS_DB_PASSWORD_FILE:?" in override


def test_release_gate_validates_compose_secrets():
    workflow = (PROJECT_ROOT / ".github/workflows/release-gate.yml").read_text(
        encoding="utf-8"
    )

    assert "OCTOHUBS_DB_PASSWORD_FILE=/dev/null" in workflow
    assert "docker-compose.secrets.yml config --quiet" in workflow
    assert "ADMIN_PASSWORD_FILE=/dev/null" in workflow
    assert "docker-compose.admin-bootstrap.yml config --quiet" in workflow
    assert "run_compose_secret_smoke.sh" not in workflow


def test_application_prefers_the_mounted_database_password_file(monkeypatch, tmp_path):
    secret_file = tmp_path / "octohubs_db_password"
    secret_file.write_text("file-only-password\n", encoding="utf-8")
    monkeypatch.setenv("OCTOHUBS_DB_PASSWORD", "environment-fallback")
    monkeypatch.setenv("OCTOHUBS_DB_PASSWORD_FILE", str(secret_file))

    assert octohubs_secret("OCTOHUBS_DB_PASSWORD") == "file-only-password"
