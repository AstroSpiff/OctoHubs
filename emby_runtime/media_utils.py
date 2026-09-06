# emby_runtime/media_utils.py
from typing import Any, Dict, Optional

from core import config_manager
from core.config import _merge_resolution_settings
from core.utils import normalize_string, _resolution_label_from_dims as _resolution_label_from_dims_utils
from emby_runtime.media_formatting import (
    _detect_audio_format,
    _detect_hdr_type,
    _format_audio_details,
    _format_video_details,
)

__all__ = [
    "_detect_audio_format",
    "_detect_hdr_type",
    "_extract_emby_media_sources",
    "_format_audio_details",
    "_format_video_details",
]


def _normalize_media_source_id(value):
    if not value:
        return ""
    return str(value).strip()


def _parse_resolution_height(value):
    if not value:
        return 0
    if isinstance(value, (int, float)):
        return int(value)
    text = normalize_string(value)
    if "x" in text:
        parts = text.split("x")
        try:
            return int(float(parts[-1]))
        except (TypeError, ValueError):
            return 0
    if text.endswith("p"):
        digits = "".join(ch for ch in text if ch.isdigit())
        try:
            return int(digits)
        except (TypeError, ValueError):
            return 0
    return 0


def _get_resolution_rules(config: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    if not isinstance(config, dict):
        config = config_manager._ACTIVE_CONFIG or {}
    return _merge_resolution_settings(config.get("RESOLUTION_RULES"))


def _parse_bitrate_mbps(value):
    if value is None:
        return 0.0
    if isinstance(value, (int, float)):
        bitrate = float(value)
    else:
        text = str(value)
        digits = []
        dot_seen = False
        for ch in text:
            if ch.isdigit():
                digits.append(ch)
            elif ch == "." and not dot_seen:
                digits.append(ch)
                dot_seen = True
        try:
            bitrate = float("".join(digits)) if digits else 0.0
        except ValueError:
            bitrate = 0.0
    if bitrate >= 1_000_000:
        return bitrate / 1_000_000
    if bitrate >= 1_000:
        return bitrate / 1_000
    return bitrate


def _version_quality_key(version):
    if not isinstance(version, dict):
        return (0, 0.0)
    height = _parse_resolution_height(version.get("resolution") or version.get("quality") or "")
    bitrate = _parse_bitrate_mbps(version.get("bitrate"))
    return (height, bitrate)


def _sort_versions_by_quality(versions):
    valid_versions = [entry for entry in versions if isinstance(entry, dict)]
    return sorted(valid_versions, key=_version_quality_key, reverse=True)


def _resolution_label_from_dims(width, height, rules: Optional[Dict[str, Any]] = None):
    if rules is None:
        rules = _get_resolution_rules()
    return _resolution_label_from_dims_utils(width, height, rules)

def _extract_emby_media_sources(item):
    sources = []
    if not isinstance(item, dict):
        return sources
    resolution_rules = _get_resolution_rules()
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
        stream_entries = []
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
