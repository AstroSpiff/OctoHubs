"""Security regressions for the server-side torrent downloader."""

from __future__ import annotations

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import socket
import threading

from search import torrent_download


class _Response:
    def __init__(self, *, status=200, headers=None, chunks=None):
        self.status = status
        self._headers = headers or {}
        self._chunks = list(chunks or [])
        self.closed = False

    def getheaders(self):
        return list(self._headers.items())

    def read(self, size):
        assert size > 0
        return self._chunks.pop(0) if self._chunks else b""

    def close(self):
        self.closed = True


class _Connection:
    def __init__(self):
        self.closed = False

    def close(self):
        self.closed = True


def _address(ip, port=443):
    family = socket.AF_INET6 if ":" in ip else socket.AF_INET
    sockaddr = (ip, port, 0, 0) if family == socket.AF_INET6 else (ip, port)
    return [(family, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", sockaddr)]


def _fake_open(responses, captured=None):
    def open_response(target):
        if captured is not None:
            captured.append(target)
        return _Connection(), responses.pop(0)

    return open_response


def test_torrent_download_blocks_loopback_before_request(monkeypatch):
    requested = []
    monkeypatch.setattr(
        torrent_download,
        "_open_pinned_response",
        lambda target: requested.append(target),
    )

    download, error = torrent_download.download_torrent("http://127.0.0.1/private")

    assert download is None
    assert error == "Destinazione download non consentita"
    assert requested == []


def test_torrent_download_revalidates_redirect_destination(monkeypatch):
    monkeypatch.setattr(
        torrent_download.socket,
        "getaddrinfo",
        lambda host, *_args, **_kwargs: _address(
            "93.184.216.34" if host == "public.example" else "169.254.169.254"
        ),
    )
    responses = [
        _Response(status=302, headers={"Location": "http://metadata.internal/latest"})
    ]
    captured = []
    monkeypatch.setattr(
        torrent_download,
        "_open_pinned_response",
        _fake_open(responses, captured),
    )

    download, error = torrent_download.download_torrent(
        "https://public.example/file.torrent"
    )

    assert download is None
    assert error == "Destinazione download non consentita"
    assert len(captured) == 1
    assert responses == []


def test_torrent_download_stops_after_size_limit(monkeypatch):
    monkeypatch.setattr(
        torrent_download.socket,
        "getaddrinfo",
        lambda *_args, **_kwargs: _address("93.184.216.34"),
    )
    response = _Response(
        chunks=[b"a" * torrent_download.MAX_TORRENT_BYTES, b"b"]
    )
    connection = _Connection()
    monkeypatch.setattr(
        torrent_download,
        "_open_pinned_response",
        lambda _target: (connection, response),
    )

    download, error = torrent_download.download_torrent(
        "https://public.example/file.torrent"
    )

    assert download is None
    assert error == "File torrent troppo grande"
    assert response.closed is True
    assert connection.closed is True


def test_torrent_download_pins_first_dns_result_against_rebinding(monkeypatch):
    dns_calls = []

    def rebinding_dns(host, *_args, **_kwargs):
        dns_calls.append(host)
        if len(dns_calls) == 1:
            return _address("93.184.216.34", 80)
        return _address("127.0.0.1", 80)

    opened = []

    class FakePinnedHTTPConnection:
        def __init__(self, endpoint, hostname, port):
            opened.append((endpoint.address, hostname, port))
            self.sock = None

        def request(self, method, target, headers):
            opened.append((method, target, headers))

        def getresponse(self):
            return _Response(chunks=[b"PUBLIC_RESPONSE"])

        def close(self):
            return None

    monkeypatch.setattr(torrent_download.socket, "getaddrinfo", rebinding_dns)
    monkeypatch.setattr(
        torrent_download,
        "_PinnedHTTPConnection",
        FakePinnedHTTPConnection,
    )

    download, error = torrent_download.download_torrent(
        "http://rebind.example/file.torrent"
    )

    assert error is None
    assert download is not None
    assert download.content == b"PUBLIC_RESPONSE"
    assert dns_calls == ["rebind.example"]
    assert opened[0] == ("93.184.216.34", "rebind.example", 80)


def test_pinned_transport_connects_without_second_name_resolution(monkeypatch):
    received_hosts = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            received_hosts.append(self.headers.get("Host"))
            self.send_response(200)
            self.send_header("Content-Length", "7")
            self.end_headers()
            self.wfile.write(b"torrent")

        def log_message(self, _format, *_args):
            return None

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    endpoint = torrent_download._ResolvedEndpoint(
        family=socket.AF_INET,
        socktype=socket.SOCK_STREAM,
        proto=socket.IPPROTO_TCP,
        sockaddr=("127.0.0.1", server.server_port),
        address="127.0.0.1",
    )
    target = torrent_download._ResolvedTarget(
        scheme="http",
        hostname="public.example",
        port=server.server_port,
        request_target="/file.torrent",
        host_header=f"public.example:{server.server_port}",
        endpoints=(endpoint,),
    )
    monkeypatch.setattr(
        torrent_download.socket,
        "getaddrinfo",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("pinned transport must not resolve DNS")
        ),
    )

    try:
        connection, response = torrent_download._open_pinned_response(target)
        try:
            assert response.read() == b"torrent"
        finally:
            response.close()
            connection.close()
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)

    assert received_hosts == [f"public.example:{server.server_port}"]


def test_https_connection_preserves_hostname_for_sni_and_host_header(monkeypatch):
    monkeypatch.setattr(
        torrent_download.socket,
        "getaddrinfo",
        lambda *_args, **_kwargs: _address("93.184.216.34"),
    )
    resolved = torrent_download._resolve_public_target(
        "https://cdn.example:8443/files/item.torrent?token=one"
    )
    assert resolved is not None
    tls_connection = torrent_download._PinnedHTTPSConnection(
        resolved.endpoints[0],
        resolved.hostname,
        resolved.port,
    )
    try:
        assert tls_connection.host == "cdn.example"
        assert tls_connection._context.check_hostname is True
        assert tls_connection._context.verify_mode == torrent_download.ssl.CERT_REQUIRED
        assert tls_connection._create_connection.__self__ is tls_connection
    finally:
        tls_connection.close()

    opened = []

    class FakePinnedHTTPSConnection:
        def __init__(self, endpoint, hostname, port):
            opened.append((endpoint.address, hostname, port))
            self.sock = None

        def request(self, method, target, headers):
            opened.append((method, target, headers))

        def getresponse(self):
            return _Response(chunks=[b"torrent"])

        def close(self):
            return None

    monkeypatch.setattr(
        torrent_download,
        "_PinnedHTTPSConnection",
        FakePinnedHTTPSConnection,
    )

    download, error = torrent_download.download_torrent(
        "https://cdn.example:8443/files/item.torrent?token=one"
    )

    assert error is None
    assert download is not None
    assert opened[0] == ("93.184.216.34", "cdn.example", 8443)
    assert opened[1] == (
        "GET",
        "/files/item.torrent?token=one",
        {"Host": "cdn.example:8443", "Accept-Encoding": "identity"},
    )


def test_torrent_download_rejects_mixed_public_and_private_dns(monkeypatch):
    addresses = _address("93.184.216.34") + _address("10.0.0.4")
    monkeypatch.setattr(
        torrent_download.socket,
        "getaddrinfo",
        lambda *_args, **_kwargs: addresses,
    )
    requested = []
    monkeypatch.setattr(
        torrent_download,
        "_open_pinned_response",
        lambda target: requested.append(target),
    )

    download, error = torrent_download.download_torrent(
        "https://mixed.example/file.torrent"
    )

    assert download is None
    assert error == "Destinazione download non consentita"
    assert requested == []
