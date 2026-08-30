"""Security contracts for Docker Compose ingress and runtime identity."""

from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_application_uses_non_root_identity_without_a_public_host_port():
    compose = (PROJECT_ROOT / "docker-compose.yml").read_text(encoding="utf-8")

    assert 'user: "${OCTOHUBS_UID:-1000}:${OCTOHUBS_GID:-1000}"' in compose
    assert 'user: "${OCTOHUBS_UID:-0}:${OCTOHUBS_GID:-0}"' not in compose
    assert 'expose:\n      - "5050"' in compose
    assert '- "5050:5050"' not in compose


def test_direct_access_requires_an_explicit_loopback_only_override():
    override = (PROJECT_ROOT / "docker-compose.direct.yml").read_text(
        encoding="utf-8"
    )

    assert "OCTOHUBS_DIRECT_BIND_ADDRESS:-127.0.0.1" in override
    assert "OCTOHUBS_DIRECT_PORT:-5050" in override
    assert "0.0.0.0" not in override


def test_nginx_is_the_explicit_public_proxy_profile():
    compose = (PROJECT_ROOT / "docker-compose.yml").read_text(encoding="utf-8")

    assert 'profiles: ["proxy"]' in compose
    assert 'server app:5050;' in (PROJECT_ROOT / "nginx.conf").read_text(
        encoding="utf-8"
    )


def test_docker_build_context_excludes_all_environment_files():
    dockerignore_lines = {
        line.strip()
        for line in (PROJECT_ROOT / ".dockerignore").read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    }

    assert ".env" in dockerignore_lines
    assert ".env.*" in dockerignore_lines
    assert not any(line.startswith("!.env") for line in dockerignore_lines)
