"""Audit trails must not trust spoofable proxy headers by default."""

from __future__ import annotations

from types import SimpleNamespace


def test_audit_ip_uses_forwarded_headers_only_when_proxy_trust_is_enabled(
    tmp_path,
    monkeypatch,
):
    from core import auth

    previous_session = auth.db_session
    auth.init_auth(
        create_default_admin=False,
        database_url=f"sqlite:///{tmp_path / 'audit-ip.db'}",
        allow_sqlite_for_tests=True,
    )
    try:
        user = auth.create_user("auditor", "password", role="admin")
        request = SimpleNamespace(
            headers={
                "X-Real-IP": "198.51.100.8",
                "X-Forwarded-For": "203.0.113.9, 172.18.0.2",
            },
            client=SimpleNamespace(host="172.18.0.2"),
            url=SimpleNamespace(path="/account"),
            scope={},
            method="POST",
        )

        monkeypatch.delenv("LOGIN_TRUST_PROXY_HEADERS", raising=False)
        auth.log_audit_event(user, "direct", request_obj=request)
        monkeypatch.setenv("LOGIN_TRUST_PROXY_HEADERS", "true")
        monkeypatch.setenv("LOGIN_TRUSTED_PROXY_CIDRS", "172.18.0.0/16")
        auth.log_audit_event(user, "proxied", request_obj=request)

        entries = auth.db_session.query(auth.AuditLog).order_by(auth.AuditLog.id).all()
        assert [entry.ip_address for entry in entries] == [
            "172.18.0.2",
            "198.51.100.8",
        ]
    finally:
        auth.shutdown_auth()
        auth.db_session = previous_session


def test_audit_truncates_oversized_user_agent_without_losing_the_entry(tmp_path):
    from core import auth

    previous_session = auth.db_session
    auth.init_auth(
        create_default_admin=False,
        database_url=f"sqlite:///{tmp_path / 'audit-agent.db'}",
        allow_sqlite_for_tests=True,
    )
    try:
        user = auth.create_user("auditor", "password", role="admin")
        request = SimpleNamespace(
            headers={"User-Agent": "x" * 10_000},
            client=SimpleNamespace(host="127.0.0.1"),
            url=SimpleNamespace(path="/account"),
            scope={},
            method="GET",
        )

        auth.log_audit_event(user, "oversized-agent", request_obj=request)

        entry = auth.db_session.query(auth.AuditLog).one()
        assert entry.action == "oversized-agent"
        assert entry.user_agent == "x" * 255
    finally:
        auth.shutdown_auth()
        auth.db_session = previous_session
