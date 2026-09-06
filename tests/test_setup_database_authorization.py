import inspect
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException


class _Templates:
    def TemplateResponse(self, _request, name, context):
        return {"template": name, "context": context}


def _initialize_routes(*, has_users=True):
    from services import setup_routes

    setup_routes.init_setup_routes(
        has_users=lambda: has_users,
        templates=_Templates(),
    )
    return setup_routes


@pytest.mark.anyio
async def test_setup_index_redirects_initialized_installation_to_login():
    routes = _initialize_routes()

    response = await routes.setup_index_route(SimpleNamespace())

    assert response.status_code == 303
    assert response.headers["location"] == "/login"


@pytest.mark.anyio
async def test_setup_user_lookup_runs_outside_the_event_loop_thread():
    from services import setup_routes

    caller_thread = threading.get_ident()
    worker_threads = []
    setup_routes.init_setup_routes(
        has_users=lambda: worker_threads.append(threading.get_ident()) or True,
        templates=_Templates(),
    )

    response = await setup_routes.setup_index_route(SimpleNamespace())

    assert response.status_code == 303
    assert worker_threads and worker_threads[0] != caller_thread


@pytest.mark.anyio
async def test_setup_user_redirects_initialized_installation_to_login():
    routes = _initialize_routes()

    response = await routes.setup_user_get_route(SimpleNamespace())

    assert response.status_code == 303
    assert response.headers["location"] == "/login"


@pytest.mark.anyio
async def test_retired_database_setup_get_redirects_to_login():
    routes = _initialize_routes()

    response = await routes.setup_db_get_route(SimpleNamespace())

    assert response.status_code == 303
    assert response.headers["location"] == "/login"


@pytest.mark.anyio
async def test_retired_database_setup_post_is_gone_without_processing_a_form():
    routes = _initialize_routes()

    with pytest.raises(HTTPException) as error:
        await routes.setup_db_post_route(SimpleNamespace())

    assert error.value.status_code == 410
    assert "OCTOHUBS_DB_*" in error.value.detail
    assert list(inspect.signature(routes.setup_db_post_route).parameters) == ["request"]


@pytest.mark.anyio
async def test_retired_database_setup_without_users_shows_bootstrap_instructions():
    routes = _initialize_routes(has_users=False)

    response = await routes.setup_db_get_route(SimpleNamespace())

    assert response.status_code == 303
    assert response.headers["location"] == "/setup/user"


def test_setup_template_has_no_database_form_or_connection_fields():
    template = Path("templates/setup.html").read_text(encoding="utf-8")

    assert 'form action="/setup/db"' not in template
    assert 'name="db_host"' not in template
    assert 'name="db_password"' not in template
    assert "OCTOHUBS_DB_*" in template
