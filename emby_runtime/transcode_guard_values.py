"""Value parsing and message formatting for Transcode Guard."""

from __future__ import annotations

from datetime import datetime, timezone
from ipaddress import ip_address, ip_network
from typing import Any, Dict, Iterable, List, Optional

from emby_runtime.transcode_guard_rules import DEFAULT_TRANSCODE_GUARD_SETTINGS

def _parse_datetime(value: Any) -> Optional[datetime]:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str) and value.strip():
        text = value.strip()
        if len(text) == 10 and text.count("-") == 2:
            text = f"{text}T00:00:00"
        try:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            return None
    else:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _extract_video_height(stream: Dict[str, Any]) -> Optional[int]:
    for key in ("video_height", "height", "source_height"):
        value = stream.get(key)
        try:
            height = int(value)
        except (TypeError, ValueError):
            continue
        return height if height > 0 else None
    label = str(stream.get("video_label") or "")
    marker = "p"
    for part in label.replace("x", " ").replace("/", " ").split():
        cleaned = part.lower().strip()
        if cleaned.endswith(marker):
            cleaned = cleaned[:-1]
        try:
            height = int(cleaned)
        except ValueError:
            continue
        if 240 <= height <= 4320:
            return height
    return None


def _is_direct_mode(value: Any) -> bool:
    text = str(value or "").strip().lower()
    return text in {"diretta", "direct", "directplay", "directstream", "direct play", "direct stream"}


def _looks_like_remux(stream: Dict[str, Any]) -> bool:
    source_container = _normalize_container_name(stream.get("container") or stream.get("stream_container"))
    output_container = _normalize_container_name(stream.get("transcode_container"))
    if output_container and source_container:
        return output_container != source_container
    stream_container = _normalize_container_name(stream.get("stream_container"))
    if stream_container and source_container:
        return stream_container != source_container
    return False


def _normalize_container_name(value: Any) -> str:
    text = str(value or "").strip().lower()
    aliases = {
        "matroska": "mkv",
        "mpegts": "ts",
        "mpeg-ts": "ts",
        "m3u8": "hls",
    }
    return aliases.get(text, text)


def _has_subtitle_burn_reason(reasons: Iterable[str]) -> bool:
    return any("subtitle" in reason.lower() or "burn" in reason.lower() for reason in reasons)


def _matches_any(value: str, patterns: Iterable[str]) -> bool:
    value_norm = str(value or "").strip().lower()
    if not value_norm:
        return False
    return any(value_norm == str(pattern or "").strip().lower() for pattern in patterns or [])


def _ip_matches_any(value: str, patterns: Iterable[str]) -> bool:
    text = str(value or "").strip()
    if not text:
        return False
    host = text
    if host.count(":") == 1 and "." in host:
        host = host.rsplit(":", 1)[0]
    try:
        address = ip_address(host)
    except ValueError:
        return _matches_any(text, patterns)
    for pattern in patterns or []:
        item = str(pattern or "").strip()
        if not item:
            continue
        try:
            if "/" in item:
                if address in ip_network(item, strict=False):
                    return True
            elif address == ip_address(item):
                return True
        except ValueError:
            if _matches_any(text, [item]):
                return True
    return False


def _normalize_string_list(value: Any) -> List[str]:
    if value is None:
        return []
    if isinstance(value, str):
        parts = value.split(",")
    elif isinstance(value, (list, tuple, set)):
        parts = value
    else:
        parts = [value]
    result = []
    for part in parts:
        text = str(part or "").strip()
        if text and text not in result:
            result.append(text)
    return result


def _to_bool(value: Any, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return bool(default)
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "on", "si", "sì"}:
        return True
    if text in {"0", "false", "no", "off"}:
        return False
    return bool(default)


def _bounded_int(value: Any, minimum: int, maximum: int, default: int) -> int:
    try:
        resolved = int(value)
    except (TypeError, ValueError):
        return int(default)
    return max(minimum, min(maximum, resolved))


def _format_message_value(
    template: Any,
    settings: Dict[str, Any],
    server: Dict[str, Any],
    stream: Dict[str, Any],
    *,
    fallback: str,
) -> str:
    text = str(template or fallback or "")
    replacements = _message_replacements(settings, server, stream)
    try:
        return text.format(**replacements)
    except Exception:
        return str(fallback or "").format(**replacements)


def _format_message(settings: Dict[str, Any], server: Dict[str, Any], stream: Dict[str, Any]) -> str:
    return _format_message_value(
        settings.get("message_text"),
        settings,
        server,
        stream,
        fallback=DEFAULT_TRANSCODE_GUARD_SETTINGS["message_text"],
    )


def _message_replacements(settings: Dict[str, Any], server: Dict[str, Any], stream: Dict[str, Any]) -> Dict[str, Any]:
    reasons = _normalize_string_list(stream.get("transcode_reasons"))
    stop_delay_seconds = settings.get("correction_window_seconds") if settings.get("mode") == "warn_then_stop" else 0
    replacements = {
        "title": stream.get("title") or "Stream",
        "server": _server_label(server),
        "user": stream.get("user") or "Utente",
        "client": stream.get("client") or "Client",
        "device": stream.get("device") or "Device",
        "reasons": ", ".join(reasons) if reasons else "Transcode video",
        "quality": f"{_extract_video_height(stream) or '?'}p",
        "seconds": stop_delay_seconds or 0,
    }
    return replacements


def _server_label(server: Dict[str, Any]) -> str:
    return (
        str(server.get("alias") or "").strip()
        or str(server.get("original_name") or "").strip()
        or str(server.get("name") or "").strip()
        or str(server.get("id") or "").strip()
        or "Server Emby"
    )
