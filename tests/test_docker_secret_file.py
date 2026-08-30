"""Contracts for the optional Docker Compose database-password secret."""

from pathlib import Path

from core.env import octohubs_secret


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_compose_secret_is_shared_without_plain_password_environment():
    override = (PROJECT_ROOT / "docker-compose.secrets.yml").read_text(
        encoding="utf-8"
    )

    assert 'OCTOHUBS_DB_PASSWORD: ""' in override
    assert "OCTOHUBS_DB_PASSWORD_FILE: /run/secrets/octohubs_db_password" in override
    assert 'POSTGRES_PASSWORD: ""' in override
    assert "POSTGRES_PASSWORD_FILE: /run/secrets/octohubs_db_password" in override
    assert override.count("- octohubs_db_password") == 2
    assert "file: ${OCTOHUBS_DB_PASSWORD_FILE:?" in override

    smoke = (PROJECT_ROOT / "scripts/run_compose_secret_smoke.sh").read_text(
        encoding="utf-8"
    )
    assert "docker-compose.secrets.yml" in smoke
    assert "docker-compose.secret-smoke.yml" in smoke
    assert "down --volumes --remove-orphans" in smoke


def test_application_prefers_the_mounted_database_password_file(monkeypatch, tmp_path):
    secret_file = tmp_path / "octohubs_db_password"
    secret_file.write_text("file-only-password\n", encoding="utf-8")
    monkeypatch.setenv("OCTOHUBS_DB_PASSWORD", "environment-fallback")
    monkeypatch.setenv("OCTOHUBS_DB_PASSWORD_FILE", str(secret_file))

    assert octohubs_secret("OCTOHUBS_DB_PASSWORD") == "file-only-password"
