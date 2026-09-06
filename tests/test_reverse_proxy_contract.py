"""Contracts for optional, operator-managed reverse proxies."""

from pathlib import Path

from web.security_headers import CONTENT_SECURITY_POLICY


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_octohubs_ships_no_reverse_proxy_runtime():
    compose = (PROJECT_ROOT / "docker-compose.yml").read_text(encoding="utf-8")

    assert "nginx:" not in compose.lower()
    assert "profiles:" not in compose
    assert not (PROJECT_ROOT / "nginx.conf").exists()


def test_external_proxy_documentation_covers_realtime_and_forwarded_headers():
    for relative_path in ("docs/DOCKER_DEPLOY.md", "docs/DOCKER_DEPLOY_ita.md"):
        documentation = (PROJECT_ROOT / relative_path).read_text(encoding="utf-8")

        for path in ("/ws/events", "/ws/scan/*", "/ws/search/*", "/ws/emby/event-bridge"):
            assert path in documentation
        assert "3600" in documentation
        assert "X-Forwarded-For" in documentation
        assert CONTENT_SECURITY_POLICY in documentation
        assert "Content-Security-Policy" in documentation


def test_uvicorn_websocket_frame_limit_matches_event_bridge_application_limit():
    dockerfile = (PROJECT_ROOT / "Dockerfile").read_text(encoding="utf-8")
    start_dev = (PROJECT_ROOT / "start_dev.sh").read_text(encoding="utf-8")

    assert '"--ws-max-size", "1048576"' in dockerfile
    assert "--ws-max-size 1048576" in start_dev


def test_environment_example_uses_runtime_database_variable_names():
    example = (PROJECT_ROOT / ".env.example").read_text(encoding="utf-8")

    assert "OCTOHUBS_DB_PASSWORD=" in example
    assert "POSTGRES_PASSWORD=" not in example
    assert "AUTH_DATABASE_URL=" not in example
