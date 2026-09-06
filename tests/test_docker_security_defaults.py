"""Security contracts for Docker Compose ingress and runtime identity."""

from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_application_uses_non_root_identity_and_loopback_http_by_default():
    compose = (PROJECT_ROOT / "docker-compose.yml").read_text(encoding="utf-8")

    assert 'user: "${OCTOHUBS_UID:-1000}:${OCTOHUBS_GID:-1000}"' in compose
    assert 'user: "${OCTOHUBS_UID:-0}:${OCTOHUBS_GID:-0}"' not in compose
    assert "OCTOHUBS_BIND_ADDRESS:-127.0.0.1" in compose
    assert "OCTOHUBS_PORT:-5050" in compose
    assert "0.0.0.0" not in compose


def test_compose_contains_no_internal_reverse_proxy():
    compose = (PROJECT_ROOT / "docker-compose.yml").read_text(encoding="utf-8")

    assert "nginx" not in compose.lower()
    assert "profiles:" not in compose
    assert not (PROJECT_ROOT / "nginx.conf").exists()
    assert not (PROJECT_ROOT / "docker-compose.direct.yml").exists()


def test_docker_build_context_excludes_all_environment_files():
    dockerignore_lines = {
        line.strip()
        for line in (PROJECT_ROOT / ".dockerignore").read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    }

    assert ".env" in dockerignore_lines
    assert ".env.*" in dockerignore_lines
    assert not any(line.startswith("!.env") for line in dockerignore_lines)


def test_runtime_has_no_unused_results_file_or_log_mount_contract():
    compose = (PROJECT_ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    dockerfile = (PROJECT_ROOT / "Dockerfile").read_text(encoding="utf-8")
    entrypoint = (PROJECT_ROOT / "docker-entrypoint.sh").read_text(encoding="utf-8")

    for content in (compose, dockerfile, entrypoint):
        assert "OCTOHUBS_RESULTS_FILE" not in content
        assert "last_results.json" not in content
        assert "/app/logs" not in content
        assert "OCTOHUBS_DB_BACKUP_DIR" not in content

    assert "/mnt/shared/applications/octohubs" not in compose


def test_cookie_secure_documentation_matches_direct_http_compose_default():
    compose = (PROJECT_ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    english = (PROJECT_ROOT / "docs/DEPLOYMENT.md").read_text(encoding="utf-8")
    italian = (PROJECT_ROOT / "docs/DEPLOYMENT_ita.md").read_text(encoding="utf-8")

    assert "SESSION_COOKIE_SECURE=${SESSION_COOKIE_SECURE:-false}" in compose
    assert "Compose defaults `SESSION_COOKIE_SECURE=false`" in english
    assert "Compose usa `SESSION_COOKIE_SECURE=false`" in italian


def test_api_token_proxy_limiter_settings_are_exposed_and_documented_bilingually():
    compose = (PROJECT_ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    example = (PROJECT_ROOT / ".env.example").read_text(encoding="utf-8")
    english = (PROJECT_ROOT / "docs/CONFIGURATION.md").read_text(encoding="utf-8")
    italian = (PROJECT_ROOT / "docs/CONFIGURATION_ita.md").read_text(encoding="utf-8")

    for name in (
        "API_TOKEN_PREAUTH_RATE_LIMIT_PER_MINUTE",
        "API_TOKEN_TRUST_PROXY_HEADERS",
        "API_TOKEN_TRUSTED_PROXY_CIDRS",
    ):
        assert name in compose
        assert name in example
        assert name in english
        assert name in italian
    assert "API_TOKEN_TRUST_PROXY_HEADERS=${API_TOKEN_TRUST_PROXY_HEADERS:-false}" in compose


def test_public_websocket_origin_is_exposed_and_documented_bilingually():
    compose = (PROJECT_ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    example = (PROJECT_ROOT / ".env.example").read_text(encoding="utf-8")
    english = (PROJECT_ROOT / "docs/DOCKER_DEPLOY.md").read_text(encoding="utf-8")
    italian = (PROJECT_ROOT / "docs/DOCKER_DEPLOY_ita.md").read_text(encoding="utf-8")

    assert "OCTOHUBS_PUBLIC_ORIGIN=${OCTOHUBS_PUBLIC_ORIGIN:-}" in compose
    assert "OCTOHUBS_PUBLIC_ORIGIN=" in example
    assert "OCTOHUBS_PUBLIC_ORIGIN" in english
    assert "OCTOHUBS_PUBLIC_ORIGIN" in italian
