import asyncio

import pytest
from sqlalchemy import text


@pytest.fixture
def initialized_auth(tmp_path):
    from core import auth

    previous_session = auth.db_session
    auth.init_auth(
        create_default_admin=False,
        database_url=f"sqlite:///{tmp_path / 'auth.db'}",
        allow_sqlite_for_tests=True,
    )
    try:
        yield auth
    finally:
        if auth.db_session is not None:
            auth.db_session.remove()
        auth.db_session = previous_session


async def _receive():
    return {"type": "http.request", "body": b"", "more_body": False}


async def _send(_message):
    return None


@pytest.mark.anyio
async def test_concurrent_requests_receive_distinct_sessions_and_both_close(initialized_auth):
    from core.auth_session_scope import current_auth_request_scope
    from web.auth_db_session_middleware import AuthDatabaseSessionMiddleware

    ready = 0
    ready_lock = asyncio.Lock()
    both_ready = asyncio.Event()
    sessions = {}

    async def app(scope, _receive, send):
        nonlocal ready
        assert current_auth_request_scope() is not None
        session = initialized_auth.db_session()
        session.execute(text("SELECT 1"))
        session.info["path"] = scope["path"]
        sessions[scope["path"]] = session
        async with ready_lock:
            ready += 1
            if ready == 2:
                both_ready.set()
        await both_ready.wait()
        assert initialized_auth.db_session().info["path"] == scope["path"]
        await send({"type": "http.response.start", "status": 204, "headers": []})
        await send({"type": "http.response.body", "body": b""})

    middleware = AuthDatabaseSessionMiddleware(app)
    await asyncio.gather(
        middleware({"type": "http", "path": "/one"}, _receive, _send),
        middleware({"type": "http", "path": "/two"}, _receive, _send),
    )

    assert sessions["/one"] is not sessions["/two"]
    assert sessions["/one"].in_transaction() is False
    assert sessions["/two"].in_transaction() is False
    assert current_auth_request_scope() is None


@pytest.mark.anyio
@pytest.mark.parametrize("scope_type", ["http", "websocket"])
async def test_session_closes_when_asgi_application_raises(initialized_auth, scope_type):
    from core.auth_session_scope import current_auth_request_scope
    from web.auth_db_session_middleware import AuthDatabaseSessionMiddleware

    sessions = []

    async def app(_scope, _receive, _send):
        session = initialized_auth.db_session()
        session.execute(text("SELECT 1"))
        sessions.append(session)
        raise RuntimeError("route failed")

    middleware = AuthDatabaseSessionMiddleware(app)
    with pytest.raises(RuntimeError, match="route failed"):
        await middleware({"type": scope_type}, _receive, _send)

    assert sessions[0].in_transaction() is False
    assert current_auth_request_scope() is None


@pytest.mark.anyio
async def test_parent_teardown_closes_session_created_in_child_task(initialized_auth):
    from web.auth_db_session_middleware import AuthDatabaseSessionMiddleware

    sessions = []

    async def child_task():
        session = initialized_auth.db_session()
        session.execute(text("SELECT 1"))
        sessions.append(session)
        raise RuntimeError("child failed")

    async def app(_scope, _receive, _send):
        task = asyncio.create_task(child_task())
        await task

    middleware = AuthDatabaseSessionMiddleware(app)
    with pytest.raises(RuntimeError, match="child failed"):
        await middleware({"type": "http"}, _receive, _send)

    assert sessions[0].in_transaction() is False
    assert initialized_auth.db_session._request_sessions == {}


def test_non_request_code_keeps_thread_scoped_session_behavior(initialized_auth):
    first = initialized_auth.db_session()
    second = initialized_auth.db_session()

    assert first is second

    initialized_auth.db_session.remove()
    assert initialized_auth.db_session() is not first
