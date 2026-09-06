from __future__ import annotations

from types import SimpleNamespace


CANARY = "sensitive-log-canary"


def test_search_query_log_value_is_redacted_and_bounded():
    from search.query_safety import MAX_SEARCH_QUERY_LOG_LENGTH, search_query_for_log

    value = f"https://user:{CANARY}@indexer.test/search?apikey={CANARY}&q=" + ("x" * 300)
    sanitized = search_query_for_log(value)

    assert CANARY not in sanitized
    assert "[REDACTED]" in sanitized
    assert len(sanitized) <= MAX_SEARCH_QUERY_LOG_LENGTH + 1

    truncated = search_query_for_log("x" * 300)
    assert truncated.endswith("…")
    assert len(truncated) == MAX_SEARCH_QUERY_LOG_LENGTH


def test_url_and_mapping_redaction_preserve_diagnostic_structure():
    from core.log_sanitization import (
        REDACTED,
        redact_mapping_for_log,
        sanitize_download_reference_for_log,
        sanitize_url_for_log,
    )

    sanitized_url = sanitize_url_for_log(
        f"wss://user:{CANARY}@emby.example:8096/embywebsocket"
        f"?api_key={CANARY}&deviceId=device-1#fragment"
    )
    sanitized_download = sanitize_download_reference_for_log(
        f"https://indexer.example/download/{CANARY}/item.torrent?apikey={CANARY}"
    )
    sanitized_config = redact_mapping_for_log(
        {
            "ENABLED": True,
            "CLIENT_ID": "public-client-id",
            "CLIENT_SECRET": CANARY,
            "nested": {"ACCESS_TOKEN": CANARY, "mode": "device"},
        }
    )

    exposed = repr((sanitized_url, sanitized_download, sanitized_config))
    assert CANARY not in exposed
    assert "wss://[REDACTED]@emby.example:8096/embywebsocket" in sanitized_url
    assert f"api_key={REDACTED}" in sanitized_url
    assert sanitized_download == f"https://indexer.example/{REDACTED}.torrent"
    assert sanitized_config["ENABLED"] is True
    assert sanitized_config["CLIENT_ID"] == "public-client-id"
    assert sanitized_config["CLIENT_SECRET"] == REDACTED
    assert sanitized_config["nested"]["mode"] == "device"


def test_text_and_nested_mapping_redact_standalone_secret_assignments():
    from core.log_sanitization import REDACTED, redact_mapping_for_log, sanitize_text_for_log

    payload = {
        "error": f"provider rejected apikey={CANARY}",
        "headers": {"Set-Cookie": f"session={CANARY}"},
    }

    sanitized_text = sanitize_text_for_log(f'{{"apikey":"{CANARY}"}}')
    sanitized_payload = redact_mapping_for_log(payload)

    assert CANARY not in sanitized_text
    assert REDACTED in sanitized_text
    assert CANARY not in repr(sanitized_payload)
    assert sanitized_payload["headers"]["Set-Cookie"] == REDACTED


def test_mdblist_response_diagnostics_redact_headers_and_body(monkeypatch, capsys):
    from emby_latest import enrichment_sources

    class Response:
        status_code = 200
        headers = {"Set-Cookie": f"session={CANARY}"}
        text = f'{{"error":"apikey={CANARY}"}}'

        def raise_for_status(self):
            return None

        def json(self):
            return {"error": f"apikey={CANARY}"}

    monkeypatch.setattr(
        enrichment_sources.requests,
        "get",
        lambda *_args, **_kwargs: Response(),
    )

    result = enrichment_sources._fetch_mdblist_ratings_by_imdb(
        "tt-r13-redaction",
        ["request-key"],
        force_refresh=True,
    )

    assert result == {}
    output = capsys.readouterr().out
    assert CANARY not in output
    assert "Response headers" in output
    assert "Raw response" in output
    assert "Parsed JSON payload" in output


def test_emby_websocket_log_redacts_key_but_connection_uses_original_url(monkeypatch):
    from emby_runtime import websocket_manager

    connected_urls = []
    log_messages = []

    class _WebSocket:
        def __init__(self, url, **_kwargs):
            connected_urls.append(url)

        def run_forever(self):
            return None

    monkeypatch.setattr(websocket_manager.websocket, "WebSocketApp", _WebSocket)
    monkeypatch.setattr(
        websocket_manager.logger,
        "info",
        lambda message, *args: log_messages.append(message % args if args else message),
    )
    connection = websocket_manager.EmbyWebSocketConnection(
        "server-1",
        "https://emby.example:8096",
        CANARY,
        lambda *_args: None,
    )

    connection._connect()

    logs = "\n".join(log_messages)
    assert CANARY in connected_urls[0]
    assert CANARY not in logs
    assert "wss://emby.example:8096/embywebsocket" in logs
    assert "api_key=[REDACTED]" in logs


def test_emby_realtime_unknown_event_logs_only_structural_context(monkeypatch, caplog, capsys):
    import logging

    from realtime import manager

    canary = "CANARY_EMBY_EVENT_SECRET"
    monkeypatch.setattr(manager, "_broadcast_sse_event", lambda _event: None)

    with caplog.at_level(logging.DEBUG, logger=manager.logger.name):
        manager._handle_emby_websocket_event(
            "server-1",
            {
                "MessageType": "PluginCustomEvent",
                "Data": {
                    "nested": {"access_token": canary},
                    "url": f"https://user:{canary}@emby.example/item?token={canary}",
                    "path": f"/private/media/{canary}/movie.mkv",
                },
            },
        )

    emitted = caplog.text + capsys.readouterr().out
    assert canary not in emitted
    assert "/private/media/" not in emitted
    assert "PluginCustomEvent" in emitted
    assert "Payload omitted" in emitted


def test_trakt_warning_keeps_config_shape_without_credentials(monkeypatch):
    from core import config

    log_messages = []
    monkeypatch.setattr(
        config.logger,
        "warning",
        lambda message, *args: log_messages.append(message % args if args else message),
    )
    merged = config._merge_trakt_settings(
        {
            "CLIENT_ID": "public-client-id",
            "CLIENT_SECRET": CANARY,
            "ACCESS_TOKEN": CANARY,
            "REFRESH_TOKEN": "",
        }
    )

    logs = "\n".join(log_messages)
    assert merged["CLIENT_SECRET"] == CANARY
    assert CANARY not in logs
    assert "CLIENT_SECRET" in logs
    assert "[REDACTED]" in logs
    assert "public-client-id" in logs


def test_indexer_debug_output_redacts_links_without_changing_results(monkeypatch, capsys):
    from emby_runtime import api_clients_indexers

    magnet = f"magnet:?xt=urn:btih:{CANARY}&dn=Private.Title&tr=https://tracker.example/{CANARY}"
    download = f"https://indexer.example/download/{CANARY}/item.torrent?apikey={CANARY}"

    class _Response:
        status_code = 200

        def raise_for_status(self):
            return None

        def json(self):
            return [
                {
                    "title": "Visible diagnostic title",
                    "magnetUrl": magnet,
                    "downloadUrl": download,
                    "infoUrl": f"https://indexer.example/details/1?apikey={CANARY}",
                    "guid": magnet,
                }
            ]

    monkeypatch.setattr(api_clients_indexers.requests, "get", lambda *_args, **_kwargs: _Response())
    results = api_clients_indexers.search_prowlarr(
        "Visible diagnostic title",
        "movie",
        {"PROWLARR_URL": "https://indexer.example", "PROWLARR_API_KEY": CANARY},
    )

    output = capsys.readouterr().out
    assert results[0]["magnet"] == magnet
    assert results[0]["downloadUrl"] == download
    assert CANARY not in output
    assert "Visible diagnostic title" in output
    assert "magnet:[REDACTED]" in output
    assert "https://indexer.example/[REDACTED].torrent" in output


def test_qbittorrent_output_redacts_submitted_magnet(monkeypatch, capsys):
    from emby_runtime import api_clients_qbittorrent

    magnet = f"magnet:?xt=urn:btih:{CANARY}&dn=Private.Title"

    class _Response:
        def __init__(self, status_code=200, text="Ok.", payload=None):
            self.status_code = status_code
            self.text = text
            self._payload = payload

        def json(self):
            return self._payload

    class _Session:
        def post(self, url, **_kwargs):
            if url.endswith("/auth/login"):
                return _Response()
            return _Response(text="Ok.")

        def get(self, *_args, **_kwargs):
            return _Response(payload=[])

    monkeypatch.setattr(api_clients_qbittorrent.requests, "Session", _Session)
    monkeypatch.setattr(api_clients_qbittorrent.time, "sleep", lambda *_args: None)

    success, _message = api_clients_qbittorrent.send_to_qbittorrent(
        magnet,
        {
            "QBITTORRENT_URL": "https://qbittorrent.example",
            "QBITTORRENT_USERNAME": "user",
            "QBITTORRENT_PASSWORD": CANARY,
        },
        max_retries=0,
    )

    output = capsys.readouterr().out
    assert success is True
    assert CANARY not in output
    assert "magnet:[REDACTED]" in output


def test_mdblist_empty_response_log_redacts_api_key(monkeypatch):
    from emby_collections import sources_mdblist

    log_messages = []
    monkeypatch.setattr(
        sources_mdblist.logger,
        "warning",
        lambda message, *args: log_messages.append(message % args if args else message),
    )
    client = sources_mdblist.MdblistClient(CANARY)
    monkeypatch.setattr(
        client,
        "_request",
        lambda _url: SimpleNamespace(text="", headers={}),
    )

    assert client.get_list("list-1") is None

    logs = "\n".join(log_messages)
    assert CANARY not in logs
    assert "apikey=[REDACTED]" in logs
