"""
Media source parsing utilities for Latest Publications.
"""

from typing import Any, Dict, List, Optional

from config import _merge_resolution_settings
from utils import DEFAULT_RESOLUTION_RULES, _resolution_label_from_dims


def get_resolution_rules(config: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    if not isinstance(config, dict):
        return DEFAULT_RESOLUTION_RULES
    rules = config.get("RESOLUTION_RULES")
    merged = _merge_resolution_settings(rules)
    return merged if isinstance(merged, dict) else DEFAULT_RESOLUTION_RULES


def _normalize_media_source_id(value: Any) -> str:
    if not value:
        return ""
    return str(value).strip()


def _detect_hdr_type(streams: Any) -> str:
    """
    Detect HDR/Dolby Vision type from video streams.
    """
    if not isinstance(streams, list):
        return ""

    for stream in streams:
        stream_type = (stream.get("type") or "").lower() if isinstance(stream, dict) else ""
        if not isinstance(stream, dict) or stream_type != "video":
            continue

        hdr_type = str(stream.get("hdr_type") or "").upper()
        video_range = str(stream.get("video_range") or "").upper()
        color_transfer = str(stream.get("color_transfer") or "").upper()

        if "DOLBY" in hdr_type or "DOVI" in hdr_type or "DV" in hdr_type:
            return "Dolby Vision"
        if "DOLBY" in video_range or "DOVI" in video_range:
            return "Dolby Vision"

        if "HDR10+" in hdr_type or "HDR10PLUS" in hdr_type:
            return "HDR10+"
        if "SMPTE2094" in color_transfer:
            return "HDR10+"

        if "HDR10" in hdr_type:
            return "HDR10"
        if "HDR" in video_range or "SMPTE2084" in color_transfer:
            return "HDR10"

        if "HDR" in hdr_type:
            return "HDR"

    return ""


def _detect_audio_format(codec: Any, channels: Any, title: str = "") -> str:
    """
    Detect advanced audio format (Atmos, DTS:X, etc).
    """
    codec_upper = (codec or "").upper()
    title_upper = (title or "").upper()

    if "ATMOS" in codec_upper or "ATMOS" in title_upper:
        return "Dolby Atmos"

    if "DTS:X" in codec_upper or "DTS:X" in title_upper or "DTSX" in codec_upper:
        return "DTS:X"

    if "DTS-HD MA" in codec_upper or "DTSHD MA" in codec_upper or "DTSHDMA" in codec_upper:
        if channels and channels >= 6:
            return f"DTS-HD MA {channels-1}.1"
        return "DTS-HD MA"

    if "TRUEHD" in codec_upper or "TRUE-HD" in codec_upper:
        if channels and channels >= 6:
            return f"Dolby TrueHD {channels-1}.1"
        return "Dolby TrueHD"

    if "EAC3" in codec_upper or "E-AC-3" in codec_upper or "DD+" in codec_upper:
        if channels and channels >= 6:
            return f"Dolby Digital+ {channels-1}.1"
        return "Dolby Digital+"

    if "AC3" in codec_upper or "AC-3" in codec_upper or "DOLBY DIGITAL" in title_upper:
        if channels and channels >= 6:
            return f"Dolby Digital {channels-1}.1"
        return "Dolby Digital"

    if "DTS" in codec_upper:
        if channels and channels >= 6:
            return f"DTS {channels-1}.1"
        return "DTS"

    if "AAC" in codec_upper:
        if channels and channels >= 6:
            return f"AAC {channels-1}.1"
        return "AAC"

    if codec and channels and channels >= 6:
        return f"{codec} {channels-1}.1"
    if codec:
        return str(codec)

    return ""


def _format_video_details(streams: Any) -> str:
    """
    Format video details for notifications.
    Example: "HEVC · HDR10 · Dolby Vision"
    """
    if not isinstance(streams, list):
        return ""

    parts: List[str] = []
    video_stream = None
    for stream in streams:
        stream_type = (stream.get("type") or "").lower() if isinstance(stream, dict) else ""
        if isinstance(stream, dict) and stream_type == "video":
            video_stream = stream
            break

    if not video_stream:
        return ""

    codec = video_stream.get("codec", "")
    if codec:
        codec_upper = str(codec).upper()
        if codec_upper in ["H264", "AVC"]:
            parts.append("H.264")
        elif codec_upper in ["H265", "HEVC"]:
            parts.append("HEVC")
        elif codec_upper == "AV1":
            parts.append("AV1")
        elif codec_upper == "VP9":
            parts.append("VP9")
        else:
            parts.append(str(codec))

    hdr = _detect_hdr_type(streams)
    if hdr:
        parts.append(hdr)

    return " · ".join(parts) if parts else ""


def _format_audio_details(streams: Any, language_filter: Optional[str] = None) -> str:
    """
    Format audio details for notifications.
    """
    if not isinstance(streams, list):
        return ""

    audio_parts: List[str] = []

    for stream in streams:
        stream_type = (stream.get("type") or "").lower() if isinstance(stream, dict) else ""
        if not isinstance(stream, dict) or stream_type != "audio":
            continue

        language = (stream.get("language") or "").lower()

        if language_filter:
            lang_filter_lower = language_filter.lower()
            if lang_filter_lower not in language:
                lang_map = {
                    "ita": ["ita", "italian", "italiano"],
                    "eng": ["eng", "english", "inglese"],
                    "spa": ["spa", "spanish", "spagnolo", "español"],
                    "fre": ["fre", "fra", "french", "francese", "français"],
                    "ger": ["ger", "deu", "german", "tedesco", "deutsch"],
                    "jpn": ["jpn", "japanese", "giapponese"]
                }
                matched = False
                for variants in lang_map.values():
                    if lang_filter_lower in variants and any(v in language for v in variants):
                        matched = True
                        break
                if not matched:
                    continue

        lang_display = ""
        if "ita" in language or "italian" in language:
            lang_display = "Italiano"
        elif "eng" in language or "english" in language:
            lang_display = "Inglese"
        elif "spa" in language or "spanish" in language:
            lang_display = "Spagnolo"
        elif "fre" in language or "fra" in language or "french" in language:
            lang_display = "Francese"
        elif "ger" in language or "deu" in language or "german" in language:
            lang_display = "Tedesco"
        elif "jpn" in language or "japanese" in language:
            lang_display = "Giapponese"
        elif language:
            lang_display = language.capitalize()

        codec = stream.get("codec", "")
        channels = stream.get("channels")
        title = stream.get("title", "")
        audio_format = _detect_audio_format(codec, channels, title)

        track_parts = []
        if lang_display:
            track_parts.append(lang_display)
        if audio_format:
            track_parts.append(audio_format)

        if track_parts:
            audio_parts.append(" ".join(track_parts))

    return " · ".join(audio_parts) if audio_parts else ""


def _extract_emby_media_sources(
    item: Dict[str, Any],
    resolution_rules: Optional[Dict[str, Any]] = None
) -> List[Dict[str, Any]]:
    sources: List[Dict[str, Any]] = []
    if not isinstance(item, dict):
        return sources
    if resolution_rules is None:
        resolution_rules = DEFAULT_RESOLUTION_RULES
    media_sources = item.get("MediaSources")
    item_streams = item.get("MediaStreams") if isinstance(item.get("MediaStreams"), list) else []
    if not isinstance(media_sources, list) or not media_sources:
        media_sources = [{
            "MediaStreams": item_streams,
            "Path": item.get("Path"),
            "Bitrate": item.get("Bitrate")
        }]

    for source in media_sources:
        if not isinstance(source, dict):
            continue
        media_streams = source.get("MediaStreams") or []
        if not isinstance(media_streams, list):
            media_streams = []
        if not media_streams and item_streams:
            media_streams = item_streams
        video_stream = None
        audio_streams = []
        stream_entries: List[Dict[str, Any]] = []
        for idx, stream in enumerate(media_streams):
            if not isinstance(stream, dict):
                continue
            stream_type = (stream.get("Type") or "").lower()
            if stream_type == "video" and video_stream is None:
                video_stream = stream
            elif stream_type == "audio":
                audio_streams.append(stream)
            stream_entries.append({
                "type": stream_type,
                "index": idx,
                "codec": stream.get("Codec"),
                "profile": stream.get("Profile"),
                "bitrate": stream.get("BitRate") or stream.get("Bitrate"),
                "bit_depth": stream.get("BitDepth"),
                "width": stream.get("Width"),
                "height": stream.get("Height"),
                "frame_rate": stream.get("AverageFrameRate") or stream.get("RealFrameRate"),
                "language": stream.get("DisplayLanguage") or stream.get("Language"),
                "channels": stream.get("Channels"),
                "channel_layout": stream.get("ChannelLayout"),
                "sample_rate": stream.get("SampleRate"),
                "title": stream.get("DisplayTitle") or stream.get("Title"),
                "is_default": stream.get("IsDefault"),
                "is_forced": stream.get("IsForced"),
                "is_external": stream.get("IsExternal"),
                "hdr_type": stream.get("HdrType"),
                "color_space": stream.get("ColorSpace"),
                "color_transfer": stream.get("ColorTransfer"),
                "color_primaries": stream.get("ColorPrimaries"),
                "video_range": stream.get("VideoRange") or stream.get("VideoRangeType")
            })

        width = video_stream.get("Width") if isinstance(video_stream, dict) else None
        height = video_stream.get("Height") if isinstance(video_stream, dict) else None
        resolution = f"{width}x{height}" if width and height else ""
        resolution_label = _resolution_label_from_dims(width, height, resolution_rules) or resolution
        video_codec = video_stream.get("Codec") if isinstance(video_stream, dict) else ""
        audio_codec = audio_streams[0].get("Codec") if audio_streams else ""
        audio_channels = ""
        if audio_streams:
            layout = audio_streams[0].get("ChannelLayout")
            channels = audio_streams[0].get("Channels")
            if layout:
                audio_channels = str(layout)
            elif channels:
                audio_channels = str(channels)
        bitrate = source.get("Bitrate") or (video_stream.get("BitRate") if isinstance(video_stream, dict) else None)
        bitrate_mbps = round(int(bitrate) / 1_000_000, 2) if bitrate else None
        path = source.get("Path") or item.get("Path") or ""
        source_id = source.get("Id") or source.get("MediaSourceId") or ""
        source_size = source.get("Size")
        container = source.get("Container") or item.get("Container") or ""
        source_name = source.get("Name") or source.get("DisplayName") or source.get("Path") or ""

        audio_tracks = []
        for stream in audio_streams:
            codec = stream.get("Codec") or ""
            language = stream.get("DisplayLanguage") or stream.get("Language") or ""
            channels = stream.get("Channels")
            title_label = stream.get("DisplayTitle") or stream.get("Title") or ""
            parts = [part for part in [codec, language, f"{channels}ch" if channels else ""] if part]
            label = title_label or " · ".join(parts) or "Traccia audio"
            audio_tracks.append(label)

        sources.append({
            "id": str(source_id) if source_id else "",
            "resolution": resolution,
            "resolution_label": resolution_label,
            "width": width,
            "height": height,
            "video_codec": video_codec,
            "audio_codec": audio_codec,
            "audio_channels": audio_channels,
            "bitrate": bitrate,
            "bitrate_mbps": bitrate_mbps,
            "path": path,
            "size": source_size,
            "container": str(container or ""),
            "source_name": source_name,
            "audio_tracks": audio_tracks,
            "streams": stream_entries
        })

    return sources
