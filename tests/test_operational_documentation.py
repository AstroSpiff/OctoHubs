"""Contracts for the bilingual installation and operations documentation."""

from pathlib import Path
import re


PROJECT_ROOT = Path(__file__).resolve().parents[1]
GUIDE_PAIRS = (
    ("README.md", "README_ita.md"),
    ("docs/DOCKER_DEPLOY.md", "docs/DOCKER_DEPLOY_ita.md"),
    ("docs/DEPLOYMENT.md", "docs/DEPLOYMENT_ita.md"),
    ("docs/CONFIGURATION.md", "docs/CONFIGURATION_ita.md"),
    ("docs/DATABASE_MIGRATIONS.md", "docs/DATABASE_MIGRATIONS_ita.md"),
    ("docs/PASSWORD_SECRET_ROTATION.md", "docs/PASSWORD_SECRET_ROTATION_ita.md"),
    ("docs/API_EXTERNAL_ACCESS.md", "docs/API_EXTERNAL_ACCESS_ita.md"),
    ("docs/API_V1_MIGRATION.md", "docs/API_V1_MIGRATION_ita.md"),
    ("docs/RELEASE_CHECKLIST.md", "docs/RELEASE_CHECKLIST_ita.md"),
)
OPERATIONAL_GUIDES = tuple(path for pair in GUIDE_PAIRS for path in pair)
MARKDOWN_LINK = re.compile(r"\[[^\]]+\]\(([^)]+)\)")


def _read(relative_path: str) -> str:
    return (PROJECT_ROOT / relative_path).read_text(encoding="utf-8")


def test_operational_guides_have_english_and_italian_pairs():
    for english_path, italian_path in GUIDE_PAIRS:
        english = _read(english_path)
        italian = _read(italian_path)

        assert Path(italian_path).name in english
        assert Path(english_path).name in italian


def test_installation_contract_covers_database_admin_portainer_and_updates():
    english = _read("README.md") + _read("docs/DOCKER_DEPLOY.md")
    italian = _read("README_ita.md") + _read("docs/DOCKER_DEPLOY_ita.md")

    for documentation in (english, italian):
        assert "Git repository" in documentation
        assert "ADMIN_PASSWORD_FILE" in documentation
        assert "scripts/manage_users.py" in documentation
        assert "OCTOHUBS_DB_PASSWORD" in documentation
        assert "#v0.4.8" in documentation
        assert "/setup" in documentation
        assert "/health/live" in documentation
        assert "/health" in documentation
        assert "docker-compose.external-db.yml" not in documentation


def test_guides_do_not_restore_retired_database_or_cli_instructions():
    documentation = "\n".join(_read(path) for path in OPERATIONAL_GUIDES)

    assert "DATABASE.ENABLED=true" not in documentation
    assert '"PASSWORD": "octohubs_password"' not in documentation
    assert not re.search(r"(?<!scripts/)manage_users\.py", documentation)


def test_configuration_keeps_database_credentials_out_of_config_example():
    for relative_path in ("docs/CONFIGURATION.md", "docs/CONFIGURATION_ita.md"):
        documentation = _read(relative_path)

        assert "OCTOHUBS_DB_PASSWORD_FILE" in documentation
        assert "OCTOHUBS_CONFIG_DIR" in documentation
        assert "OCTOHUBS_LEGACY_AUTH_SQLITE_PATH" not in documentation
        assert '"DATABASE": {' not in documentation


def test_english_operational_guides_cover_external_api_and_release_gate():
    external_api = _read("docs/API_EXTERNAL_ACCESS.md")
    release = _read("docs/RELEASE_CHECKLIST.md")

    assert "/api/v1/external/openapi.json" in external_api
    assert "scripts/octohubs_api_client.py" in external_api
    assert "reset_required" in external_api
    assert "scripts/audit_external_api_contract.py --strict" in release
    assert "scripts/run_postgresql_release_gate.sh" in release
    assert "/health/ready" in release


def test_external_api_guides_document_the_probe_debug_scope():
    english = _read("docs/API_EXTERNAL_ACCESS.md")
    italian = _read("docs/API_EXTERNAL_ACCESS_ita.md")

    assert "debug-recent-items, scans, discovery" in english
    assert "processing and retry                           -> run:operations" in english
    assert re.search(
        r"/api/v1/emby/probe/debug-recent-items\s*-> run:operations",
        italian,
    )


def test_bilingual_guides_cover_the_same_material_operational_areas():
    external_pairs = (
        ("Technical scopes", "Scope tecnici"),
        ("Main endpoint-to-scope map", "Mappatura principali endpoint"),
        ("Curl examples", "Esempi curl"),
        ("Errors and audit", "Errori attesi"),
        ("Contract verification", "Audit del contratto v1"),
    )
    english_api = _read("docs/API_EXTERNAL_ACCESS.md")
    italian_api = _read("docs/API_EXTERNAL_ACCESS_ita.md")
    for english_heading, italian_heading in external_pairs:
        assert english_heading in english_api
        assert italian_heading in italian_api

    assert "## Emby Collections" in _read("docs/EMBY_TOOLS.md")
    assert "## Collezioni Emby" in _read("docs/EMBY_TOOLS_ita.md")


def test_historical_ui_roadmap_is_archived_and_not_in_current_navigation():
    roadmap = _read("docs/UI_API_CONTROL_ROADMAP_ita.md")
    assert "Documento storico archiviato" in roadmap
    assert "UI_API_CONTROL_ROADMAP" not in _read("README.md")
    assert "UI_API_CONTROL_ROADMAP" not in _read("README_ita.md")


def test_operational_guide_relative_links_resolve():
    broken_links = []
    for relative_path in OPERATIONAL_GUIDES:
        source = PROJECT_ROOT / relative_path
        for raw_target in MARKDOWN_LINK.findall(_read(relative_path)):
            target = raw_target.strip().split("#", 1)[0]
            if not target or "://" in target or target.startswith("mailto:"):
                continue
            if not (source.parent / target).resolve().exists():
                broken_links.append(f"{relative_path}: {raw_target}")

    assert not broken_links, "Broken documentation links: " + ", ".join(broken_links)
