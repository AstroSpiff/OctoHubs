from pathlib import Path

import pytest
from fastapi import HTTPException


@pytest.mark.anyio
async def test_browser_cannot_create_initial_administrator():
    from services import setup_routes

    setup_routes.init_setup_routes(
        has_users=lambda: False,
        templates=object(),
    )

    with pytest.raises(HTTPException) as error:
        await setup_routes.setup_user_post_route(object())

    assert error.value.status_code == 403


def test_setup_page_contains_no_administrator_creation_form():
    template = Path("templates/setup.html").read_text(encoding="utf-8")

    assert 'form action="/setup/user"' not in template
    assert "ADMIN_PASSWORD_FILE" in template


def test_compose_override_mounts_one_time_administrator_secret():
    override = Path("docker-compose.admin-bootstrap.yml").read_text(encoding="utf-8")

    assert 'ADMIN_PASSWORD: ""' in override
    assert "ADMIN_PASSWORD_FILE: /run/secrets/octohubs_admin_password" in override
    assert "file: ${ADMIN_PASSWORD_FILE:?" in override


def test_initial_administrator_can_be_bootstrapped_from_secret_file(tmp_path, monkeypatch):
    from core import auth

    password_file = tmp_path / "admin-password"
    password_file.write_text("strong-bootstrap-password\n", encoding="utf-8")
    monkeypatch.setenv("ADMIN_USERNAME", "bootstrap-admin")
    monkeypatch.setenv("ADMIN_PASSWORD", "ignored-environment-password")
    monkeypatch.setenv("ADMIN_PASSWORD_FILE", str(password_file))
    monkeypatch.setenv("ADMIN_EMAIL", "admin@example.test")

    database_url = f"sqlite:///{tmp_path / 'auth.db'}"
    assert auth.init_auth(
        create_default_admin=True,
        database_url=database_url,
        allow_sqlite_for_tests=True,
    )

    admin = auth.get_user_by_username("bootstrap-admin")
    assert admin is not None
    assert admin.get_role() == "admin"
    assert admin.check_password("strong-bootstrap-password") is True
    assert admin.check_password("ignored-environment-password") is False

    password_file.write_text("replacement-password\n", encoding="utf-8")
    assert auth.init_auth(
        create_default_admin=True,
        database_url=database_url,
        allow_sqlite_for_tests=True,
    )

    unchanged_admin = auth.get_user_by_username("bootstrap-admin")
    assert unchanged_admin is not None
    assert unchanged_admin.check_password("strong-bootstrap-password") is True
    assert unchanged_admin.check_password("replacement-password") is False
