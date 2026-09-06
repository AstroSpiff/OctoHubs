"""Canonical formatting for normalized Emby media streams."""

from __future__ import annotations

from typing import Any


_LANGUAGE_VARIANTS = {
    "ita": ("ita", "italian", "italiano"),
    "eng": ("eng", "english", "inglese"),
    "spa": ("spa", "spanish", "spagnolo", "español"),
    "fre": ("fre", "fra", "french", "francese", "français"),
    "ger": ("ger", "deu", "german", "tedesco", "deutsch"),
    "jpn": ("jpn", "japanese", "giapponese"),
}

_LANGUAGE_LABELS = {
    "ita": "Italiano",
    "eng": "Inglese",
    "spa": "Spagnolo",
    "fre": "Francese",
    "ger": "Tedesco",
    "jpn": "Giapponese",
}


def _channel_label(channels: Any) -> str:
    try:
        count = int(channels or 0)
    except (TypeError, ValueError):
        return ""
    return f"{count - 1}.1" if count >= 6 else ""


def _detect_hdr_type(streams: Any) -> str:
    """Return the first recognized HDR format in normalized stream data."""
    if not isinstance(streams, list):
        return ""
    for stream in streams:
        if not isinstance(stream, dict) or str(stream.get("type") or "").lower() != "video":
            continue
        hdr_type = str(stream.get("hdr_type") or "").upper()
        video_range = str(stream.get("video_range") or "").upper()
        color_transfer = str(stream.get("color_transfer") or "").upper()
        if any(token in hdr_type for token in ("DOLBY", "DOVI", "DV")):
            return "Dolby Vision"
        if "DOLBY" in video_range or "DOVI" in video_range:
            return "Dolby Vision"
        if "HDR10+" in hdr_type or "HDR10PLUS" in hdr_type or "SMPTE2094" in color_transfer:
            return "HDR10+"
        if "HDR10" in hdr_type or "HDR" in video_range or "SMPTE2084" in color_transfer:
            return "HDR10"
        if "HDR" in hdr_type:
            return "HDR"
    return ""


def _detect_audio_format(
    codec: Any,
    channels: Any,
    title: str = "",
    profile: str = "",
    display_title: str = "",
) -> str:
    """Return a stable display label for an audio codec and its aliases."""
    codec_text = str(codec or "")
    codec_upper = codec_text.upper()
    metadata_upper = " ".join(str(value or "") for value in (title, profile, display_title)).upper()
    combined = f"{codec_upper} {metadata_upper}"
    channel_label = _channel_label(channels)

    if "ATMOS" in combined:
        return "Dolby Atmos"
    if "DTS:X" in combined or "DTSX" in combined:
        return "DTS:X"
    if any(token in combined for token in ("DTS-HD MA", "DTSHD MA", "DTSHDMA", "DTS-HD MASTER")):
        return f"DTS-HD MA {channel_label}".strip()
    if "TRUEHD" in combined or "TRUE-HD" in combined:
        return f"Dolby TrueHD {channel_label}".strip()
    if "EAC3" in combined or "E-AC-3" in combined or "DD+" in combined:
        return f"Dolby Digital+ {channel_label}".strip()
    if "AC3" in combined or "AC-3" in combined or "DOLBY DIGITAL" in metadata_upper:
        return f"Dolby Digital {channel_label}".strip()
    if "DTS" in combined:
        return f"DTS {channel_label}".strip()
    if "AAC" in combined:
        return f"AAC {channel_label}".strip()
    if codec_text:
        return f"{codec_text} {channel_label}".strip()
    return ""


def _format_video_details(streams: Any) -> str:
    """Format codec and HDR details from normalized video streams."""
    if not isinstance(streams, list):
        return ""
    video_stream = next(
        (
            stream
            for stream in streams
            if isinstance(stream, dict) and str(stream.get("type") or "").lower() == "video"
        ),
        None,
    )
    if not video_stream:
        return ""
    codec = str(video_stream.get("codec") or "")
    codec_upper = codec.upper()
    codec_label = {
        "H264": "H.264",
        "AVC": "H.264",
        "H265": "HEVC",
        "HEVC": "HEVC",
        "AV1": "AV1",
        "VP9": "VP9",
    }.get(codec_upper, codec)
    parts = [codec_label] if codec_label else []
    hdr = _detect_hdr_type(streams)
    if hdr:
        parts.append(hdr)
    return " · ".join(parts)


def _language_key(language: str) -> str:
    for key, variants in _LANGUAGE_VARIANTS.items():
        if any(variant in language for variant in variants):
            return key
    return ""


def _language_matches(language: str, language_filter: str | None) -> bool:
    if not language_filter:
        return True
    requested = language_filter.lower()
    if requested in language:
        return True
    for variants in _LANGUAGE_VARIANTS.values():
        if requested in variants:
            return any(variant in language for variant in variants)
    return False


def _format_audio_details(streams: Any, language_filter: str | None = None) -> str:
    """Format all matching normalized audio streams consistently."""
    if not isinstance(streams, list):
        return ""
    audio_parts: list[str] = []
    for stream in streams:
        if not isinstance(stream, dict) or str(stream.get("type") or "").lower() != "audio":
            continue
        language = str(stream.get("language") or "").lower()
        if not _language_matches(language, language_filter):
            continue
        language_key = _language_key(language)
        language_label = _LANGUAGE_LABELS.get(language_key, language.capitalize() if language else "")
        audio_format = _detect_audio_format(
            stream.get("codec", ""),
            stream.get("channels"),
            str(stream.get("title") or ""),
            str(stream.get("profile") or ""),
            str(stream.get("display_title") or stream.get("DisplayTitle") or ""),
        )
        track = " ".join(part for part in (language_label, audio_format) if part)
        if track:
            audio_parts.append(track)
    return " · ".join(audio_parts)


__all__ = [
    "_detect_audio_format",
    "_detect_hdr_type",
    "_format_audio_details",
    "_format_video_details",
]
