"""Network boundary checks for server-side torrent downloads."""

from __future__ import annotations

from dataclasses import dataclass
import http.client
import ipaddress
import socket
import ssl
from typing import Any, Mapping
from urllib.parse import urljoin, urlparse, urlunsplit


MAX_TORRENT_BYTES = 10 * 1024 * 1024
MAX_REDIRECTS = 3
_CONNECT_TIMEOUT_SECONDS = 5
_READ_TIMEOUT_SECONDS = 30
_REDIRECT_STATUSES = frozenset({301, 302, 303, 307, 308})


@dataclass(frozen=True)
class TorrentDownload:
    content: bytes
    final_url: str
    headers: Mapping[str, str]


@dataclass(frozen=True)
class _ResolvedEndpoint:
    family: int
    socktype: int
    proto: int
    sockaddr: Any
    address: str


@dataclass(frozen=True)
class _ResolvedTarget:
    scheme: str
    hostname: str
    port: int
    request_target: str
    host_header: str
    endpoints: tuple[_ResolvedEndpoint, ...]


def _normalized_hostname(raw_hostname: str) -> str | None:
    try:
        return ipaddress.ip_address(raw_hostname).compressed
    except ValueError:
        pass
    try:
        hostname = raw_hostname.rstrip(".").encode("idna").decode("ascii").lower()
    except (UnicodeError, ValueError):
        return None
    return hostname or None


def _resolve_public_target(url: str) -> _ResolvedTarget | None:
    try:
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            return None
        if parsed.username is not None or parsed.password is not None:
            return None
        if any(character in url for character in ("\r", "\n", "\t")):
            return None
        hostname = _normalized_hostname(parsed.hostname)
        if not hostname:
            return None
        default_port = 443 if parsed.scheme == "https" else 80
        port = parsed.port or default_port
    except ValueError:
        return None

    try:
        address_info = socket.getaddrinfo(
            hostname,
            port,
            type=socket.SOCK_STREAM,
        )
    except OSError:
        return None

    endpoints: list[_ResolvedEndpoint] = []
    seen: set[tuple[int, Any]] = set()
    for family, socktype, proto, _canonical_name, sockaddr in address_info:
        try:
            address = str(sockaddr[0])
            if not ipaddress.ip_address(address).is_global:
                return None
        except (IndexError, TypeError, ValueError):
            return None
        key = (family, sockaddr)
        if key in seen:
            continue
        seen.add(key)
        endpoints.append(
            _ResolvedEndpoint(
                family=family,
                socktype=socktype,
                proto=proto,
                sockaddr=sockaddr,
                address=address,
            )
        )
    if not endpoints:
        return None

    display_hostname = f"[{hostname}]" if ":" in hostname else hostname
    host_header = (
        display_hostname if port == default_port else f"{display_hostname}:{port}"
    )
    request_target = urlunsplit(("", "", parsed.path or "/", parsed.query, ""))
    return _ResolvedTarget(
        scheme=parsed.scheme,
        hostname=hostname,
        port=port,
        request_target=request_target,
        host_header=host_header,
        endpoints=tuple(endpoints),
    )


class _PinnedConnectionMixin:
    _endpoint: _ResolvedEndpoint

    def _open_validated_socket(self, _address, timeout, source_address):
        endpoint = self._endpoint
        sock = socket.socket(endpoint.family, endpoint.socktype, endpoint.proto)
        try:
            if timeout is not socket._GLOBAL_DEFAULT_TIMEOUT:
                sock.settimeout(timeout)
            if source_address:
                sock.bind(source_address)
            # Connect to the validated sockaddr directly: no second DNS lookup.
            sock.connect(endpoint.sockaddr)
            return sock
        except BaseException:
            sock.close()
            raise


class _PinnedHTTPConnection(_PinnedConnectionMixin, http.client.HTTPConnection):
    def __init__(self, endpoint: _ResolvedEndpoint, hostname: str, port: int):
        self._endpoint = endpoint
        super().__init__(hostname, port=port, timeout=_CONNECT_TIMEOUT_SECONDS)
        self._create_connection = self._open_validated_socket


class _PinnedHTTPSConnection(_PinnedConnectionMixin, http.client.HTTPSConnection):
    def __init__(self, endpoint: _ResolvedEndpoint, hostname: str, port: int):
        self._endpoint = endpoint
        # The original hostname remains the TLS SNI and certificate identity.
        super().__init__(
            hostname,
            port=port,
            timeout=_CONNECT_TIMEOUT_SECONDS,
            context=ssl.create_default_context(),
        )
        self._create_connection = self._open_validated_socket


def _open_pinned_response(
    target: _ResolvedTarget,
) -> tuple[http.client.HTTPConnection, http.client.HTTPResponse]:
    last_error: BaseException | None = None
    connection_type = (
        _PinnedHTTPSConnection if target.scheme == "https" else _PinnedHTTPConnection
    )
    for endpoint in target.endpoints:
        connection = connection_type(endpoint, target.hostname, target.port)
        try:
            connection.request(
                "GET",
                target.request_target,
                headers={
                    "Host": target.host_header,
                    "Accept-Encoding": "identity",
                },
            )
            if connection.sock is not None:
                connection.sock.settimeout(_READ_TIMEOUT_SECONDS)
            return connection, connection.getresponse()
        except (OSError, http.client.HTTPException) as exc:
            last_error = exc
            connection.close()
    if last_error is not None:
        raise last_error
    raise OSError("No validated download endpoint available")


def _response_headers(response: http.client.HTTPResponse) -> dict[str, str]:
    return {name.lower(): value for name, value in response.getheaders()}


def download_torrent(url: str) -> tuple[TorrentDownload | None, str | None]:
    """Download a bounded response from the validated IP behind each URL hop."""
    current_url = url
    for redirect_count in range(MAX_REDIRECTS + 1):
        target = _resolve_public_target(current_url)
        if target is None:
            return None, "Destinazione download non consentita"
        try:
            connection, response = _open_pinned_response(target)
        except (OSError, http.client.HTTPException):
            return None, "Download torrent non riuscito"

        try:
            headers = _response_headers(response)
            if response.status in _REDIRECT_STATUSES:
                location = headers.get("location")
                if not location or redirect_count >= MAX_REDIRECTS:
                    return None, "Redirect download non valido"
                current_url = urljoin(current_url, location)
                continue
            if response.status >= 400:
                return None, "Download torrent non riuscito"

            content_length = headers.get("content-length")
            if content_length:
                try:
                    declared_size = int(content_length)
                except ValueError:
                    return None, "Dimensione download non valida"
                if declared_size < 0:
                    return None, "Dimensione download non valida"
                if declared_size > MAX_TORRENT_BYTES:
                    return None, "File torrent troppo grande"

            chunks: list[bytes] = []
            total = 0
            while True:
                chunk = response.read(64 * 1024)
                if not chunk:
                    break
                total += len(chunk)
                if total > MAX_TORRENT_BYTES:
                    return None, "File torrent troppo grande"
                chunks.append(chunk)
            return TorrentDownload(b"".join(chunks), current_url, headers), None
        except (OSError, http.client.HTTPException):
            return None, "Download torrent non riuscito"
        finally:
            response.close()
            connection.close()

    return None, "Redirect download non valido"


__all__ = ["MAX_TORRENT_BYTES", "TorrentDownload", "download_torrent"]
