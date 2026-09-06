from pathlib import Path
import re


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_base_compose_is_app_only_and_requires_an_external_database():
    compose = (PROJECT_ROOT / "docker-compose.yml").read_text(encoding="utf-8")

    assert not re.search(r"^  postgres:\s*$", compose, flags=re.MULTILINE)
    assert "depends_on:\n      postgres:" not in compose
    assert "OCTOHUBS_DB_HOST=${OCTOHUBS_DB_HOST:-}" in compose
    assert "OCTOHUBS_DB_PASSWORD=${OCTOHUBS_DB_PASSWORD:-}" in compose


def test_release_gate_rejects_a_default_database_service():
    workflow = (PROJECT_ROOT / ".github/workflows/release-gate.yml").read_text(
        encoding="utf-8"
    )

    assert "docker-compose.external-db.yml" not in workflow
    assert 'test "$base_services" = "app"' in workflow


def test_external_database_documentation_describes_operator_ownership():
    for relative_path in ("docs/DOCKER_DEPLOY.md", "docs/DOCKER_DEPLOY_ita.md"):
        documentation = (PROJECT_ROOT / relative_path).read_text(encoding="utf-8")

        assert "docker-compose.external-db.yml" not in documentation
        assert "PostgreSQL" in documentation
        assert "Portainer" in documentation

    assert "operator-managed" in (PROJECT_ROOT / "docs/DOCKER_DEPLOY.md").read_text(
        encoding="utf-8"
    )
    assert "gestito dall'operatore" in (
        PROJECT_ROOT / "docs/DOCKER_DEPLOY_ita.md"
    ).read_text(encoding="utf-8")


def test_runtime_ignores_removed_config_file_setting(monkeypatch, tmp_path):
    from core.database_connection import resolve_application_database_url

    config_path = tmp_path / "config.json"
    config_path.write_text(
        '{"DATABASE":{"ENABLED":true,"HOST":"browser-db","NAME":"split","USER":"browser"}}',
        encoding="utf-8",
    )
    monkeypatch.setenv("OCTOHUBS_CONFIG_FILE", str(config_path))
    for key in (
        "OCTOHUBS_DB_URL",
        "DATABASE_URL",
        "OCTOHUBS_DB_HOST",
        "OCTOHUBS_DB_PORT",
        "OCTOHUBS_DB_NAME",
        "OCTOHUBS_DB_USER",
        "OCTOHUBS_DB_PASSWORD",
        "OCTOHUBS_DB_DRIVER",
        "OCTOHUBS_DB_PARAMS",
    ):
        monkeypatch.delenv(key, raising=False)

    assert resolve_application_database_url() is None


def test_compose_uses_a_directory_for_generated_secrets_not_config_json():
    compose = (PROJECT_ROOT / "docker-compose.yml").read_text(encoding="utf-8")

    assert "OCTOHUBS_CONFIG_DIR=${OCTOHUBS_CONFIG_DIR:-/config}" in compose
    assert "OCTOHUBS_CONFIG_FILE" not in compose
    assert "OCTOHUBS_LEGACY_AUTH_SQLITE_PATH" not in compose


def test_configuration_database_is_read_only_in_service_write_contract():
    from pydantic import ValidationError
    from web.configuration_api_models import ConfigurationServicesUpdateRequest

    try:
        ConfigurationServicesUpdateRequest.model_validate(
            {"database": {"host": "browser-db", "name": "split", "user": "browser"}}
        )
    except ValidationError:
        pass
    else:
        raise AssertionError("browser database fields must be rejected")
