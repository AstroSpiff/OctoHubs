"""Deployment contract checks for the documented Nginx proxy."""

from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_nginx_targets_uvicorn_and_forwards_websocket_upgrade():
    config = (PROJECT_ROOT / "nginx.conf").read_text(encoding="utf-8")

    assert "server app:5050;" in config
    assert "server app:5000;" not in config
    assert "proxy_set_header Upgrade $http_upgrade;" in config
    assert "proxy_set_header Connection $connection_upgrade;" in config
    assert "map $http_upgrade $connection_upgrade" in config


def test_event_bridge_proxy_has_exact_body_and_request_limits():
    config = (PROJECT_ROOT / "nginx.conf").read_text(encoding="utf-8")

    assert "location = /api/emby/event-bridge/events" in config
    assert "location = /api/emby/transcode-guard/player-event" in config
    assert "location = /ws/emby/event-bridge" in config
    assert config.count("client_max_body_size 1m;") == 2
    assert "zone=webhook_limit:10m rate=20r/s" in config
    assert config.count("limit_req zone=webhook_limit burst=40 nodelay;") >= 4


def test_uvicorn_websocket_frame_limit_matches_event_bridge_application_limit():
    dockerfile = (PROJECT_ROOT / "Dockerfile").read_text(encoding="utf-8")

    assert '"--ws-max-size", "1048576"' in dockerfile


def test_environment_example_uses_runtime_database_variable_names():
    example = (PROJECT_ROOT / ".env.example").read_text(encoding="utf-8")

    assert "OCTOHUBS_DB_PASSWORD=" in example
    assert "POSTGRES_PASSWORD=" not in example
    assert "AUTH_DATABASE_URL=" not in example
