"""Event Bridge source-network policy."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from emby_runtime.event_bridge_network_policy import validate_event_bridge_source


def _connection(host: str, headers: dict[str, str] | None = None):
    return SimpleNamespace(
        client=SimpleNamespace(host=host),
        headers=headers or {},
    )


def test_event_bridge_allowlist_is_optional(monkeypatch):
    monkeypatch.delenv("WEBHOOK_IP_WHITELIST", raising=False)

    validate_event_bridge_source(_connection("not-an-ip"))


@pytest.mark.parametrize(
    ("allowlist", "host"),
    [
        ("192.0.2.10", "192.0.2.10"),
        ("10.10.0.0/16", "10.10.4.8"),
        ("2001:db8:abcd::/48", "2001:db8:abcd::21"),
        ("10.10.0.0/16", "::ffff:10.10.4.8"),
    ],
)
def test_event_bridge_allowlist_accepts_ips_and_cidrs(monkeypatch, allowlist, host):
    monkeypatch.setenv("WEBHOOK_IP_WHITELIST", allowlist)
    monkeypatch.delenv("WEBHOOK_TRUST_PROXY_HEADERS", raising=False)

    validate_event_bridge_source(_connection(host))


def test_event_bridge_allowlist_rejects_non_matching_source(monkeypatch):
    monkeypatch.setenv("WEBHOOK_IP_WHITELIST", "10.0.0.0/8,2001:db8::/32")

    with pytest.raises(HTTPException) as raised:
        validate_event_bridge_source(_connection("192.0.2.55"))

    assert raised.value.status_code == 403


def test_event_bridge_ignores_proxy_headers_unless_explicitly_trusted(monkeypatch):
    monkeypatch.setenv("WEBHOOK_IP_WHITELIST", "198.51.100.8")
    monkeypatch.delenv("WEBHOOK_TRUST_PROXY_HEADERS", raising=False)
    connection = _connection(
        "10.0.0.20",
        {"X-Real-IP": "198.51.100.8", "X-Forwarded-For": "198.51.100.8"},
    )

    with pytest.raises(HTTPException) as raised:
        validate_event_bridge_source(connection)

    assert raised.value.status_code == 403


def test_event_bridge_uses_x_real_ip_from_trusted_proxy(monkeypatch):
    monkeypatch.setenv("WEBHOOK_IP_WHITELIST", "198.51.100.0/24")
    monkeypatch.setenv("WEBHOOK_TRUST_PROXY_HEADERS", "true")
    connection = _connection(
        "10.0.0.20",
        {"X-Real-IP": "198.51.100.8", "X-Forwarded-For": "203.0.113.99"},
    )

    validate_event_bridge_source(connection)


@pytest.mark.parametrize("allowlist", ["not-an-ip", "10.0.0.1,,192.0.2.1"])
def test_event_bridge_invalid_allowlist_fails_closed(monkeypatch, allowlist):
    monkeypatch.setenv("WEBHOOK_IP_WHITELIST", allowlist)

    with pytest.raises(HTTPException) as raised:
        validate_event_bridge_source(_connection("10.0.0.1"))

    assert raised.value.status_code == 503
