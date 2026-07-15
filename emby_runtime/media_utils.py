# emby_runtime/media_utils.py
from typing import Any, Dict, Optional

from core import config_manager
from core.config import _merge_resolution_settings
from core.utils import normalize_string, _resolution_label_from_dims as _resolution_label_from_dims_utils


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


def _detect_hdr_type(streams):
    """
    Rileva il tipo di HDR/Dolby Vision dai dati stream video.
    Ritorna una stringa descrittiva tipo "Dolby Vision", "HDR10+", "HDR10", "HDR", o ""
    """
    if not isinstance(streams, list):
        return ""

    for stream in streams:
        stream_type = (stream.get("type") or "").lower() if isinstance(stream, dict) else ""
        if not isinstance(stream, dict) or stream_type != "video":
            continue

        # Controlla HDR Type specifico da Emby
        hdr_type = str(stream.get("hdr_type") or "").upper()
        video_range = str(stream.get("video_range") or "").upper()
        color_transfer = str(stream.get("color_transfer") or "").upper()

        # Dolby Vision detection
        if "DOLBY" in hdr_type or "DOVI" in hdr_type or "DV" in hdr_type:
            return "Dolby Vision"
        if "DOLBY" in video_range or "DOVI" in video_range:
            return "Dolby Vision"

        # HDR10+ detection
        if "HDR10+" in hdr_type or "HDR10PLUS" in hdr_type:
            return "HDR10+"
        if "SMPTE2094" in color_transfer:
            return "HDR10+"

        # HDR10 detection
        if "HDR10" in hdr_type:
            return "HDR10"
        if "HDR" in video_range or "SMPTE2084" in color_transfer:
            return "HDR10"

        # Generic HDR
        if "HDR" in hdr_type:
            return "HDR"

    return ""


def _detect_audio_format(codec, channels, title="", profile="", display_title=""):
    """
    Rileva formato audio avanzato (Atmos, DTS:X, ecc) da codec, channels e title.
    Ritorna stringa tipo "Dolby Atmos", "DTS:X", "Dolby TrueHD 7.1", ecc.
    """
    codec_upper = (codec or "").upper()
    combined_upper = " ".join([
        (title or ""), (profile or ""), (display_title or "")
    ]).upper()

    # Dolby Atmos detection
    if "ATMOS" in codec_upper or "ATMOS" in combined_upper:
        return "Dolby Atmos"

    # DTS:X detection
    if "DTS:X" in codec_upper or "DTS:X" in combined_upper or "DTSX" in codec_upper:
        return "DTS:X"

    # DTS-HD Master Audio
    if "DTS-HD MA" in codec_upper or "DTS-HD MASTER" in combined_upper:
        if channels and channels >= 6:
            return f"DTS-HD MA {channels-1}.1"
        return "DTS-HD MA"

    # Dolby TrueHD
    if "TRUEHD" in codec_upper or "TRUE-HD" in codec_upper:
        if channels and channels >= 6:
            return f"Dolby TrueHD {channels-1}.1"
        return "Dolby TrueHD"

    # Dolby Digital Plus
    if "EAC3" in codec_upper or "E-AC-3" in codec_upper or "DD+" in codec_upper:
        if channels and channels >= 6:
            return f"Dolby Digital+ {channels-1}.1"
        return "Dolby Digital+"

    # Dolby Digital (AC3)
    if "AC3" in codec_upper or "AC-3" in codec_upper or "DOLBY DIGITAL" in combined_upper:
        if channels and channels >= 6:
            return f"Dolby Digital {channels-1}.1"
        return "Dolby Digital"

    # DTS
    if "DTS" in codec_upper:
        if channels and channels >= 6:
            return f"DTS {channels-1}.1"
        return "DTS"

    # AAC
    if "AAC" in codec_upper:
        if channels and channels >= 6:
            return f"AAC {channels-1}.1"
        return "AAC"

    # Fallback: codec + channels
    if codec and channels and channels >= 6:
        return f"{codec} {channels-1}.1"
    elif codec:
        return codec

    return ""


def _format_video_details(streams):
    """
    Formatta dettagli video completi per le notifiche.
    Esempio output: "HEVC · HDR10 · Dolby Vision"
    """
    if not isinstance(streams, list):
        return ""

    parts = []

    # Trova stream video
    video_stream = None
    for stream in streams:
        stream_type = (stream.get("type") or "").lower() if isinstance(stream, dict) else ""
        if isinstance(stream, dict) and stream_type == "video":
            video_stream = stream
            break

    if not video_stream:
        return ""

    # Codec video
    codec = video_stream.get("codec", "")
    if codec:
        codec_upper = codec.upper()
        # Normalizza nomi codec comuni
        if codec_upper in ["H264", "AVC"]:
            parts.append("H.264")
        elif codec_upper in ["H265", "HEVC"]:
            parts.append("HEVC")
        elif codec_upper == "AV1":
            parts.append("AV1")
        elif codec_upper == "VP9":
            parts.append("VP9")
        else:
            parts.append(codec)

    # HDR/Dolby Vision
    hdr = _detect_hdr_type(streams)
    if hdr:
        parts.append(hdr)

    return " · ".join(parts) if parts else ""


def _format_audio_details(streams, language_filter=None):
    """
    Formatta dettagli audio per le notifiche.

    Args:
        streams: lista degli stream multimediali
        language_filter: se specificato, filtra solo questa lingua (es. "ita", "eng")

    Returns:
        Stringa formattata tipo "Italiano Dolby Atmos · Inglese DTS-HD MA 7.1"
    """
    if not isinstance(streams, list):
        return ""

    audio_parts = []

    for stream in streams:
        stream_type = (stream.get("type") or "").lower() if isinstance(stream, dict) else ""
        if not isinstance(stream, dict) or stream_type != "audio":
            continue

        language = (stream.get("language") or "").lower()

        # Filtra per lingua se richiesto
        if language_filter:
            lang_filter_lower = language_filter.lower()
            # Controlla sia codice ISO che nome completo
            if lang_filter_lower not in language:
                # Mappa comuni
                lang_map = {
                    "ita": ["ita", "italian", "italiano"],
                    "eng": ["eng", "english", "inglese"],
                    "spa": ["spa", "spanish", "spagnolo", "español"],
                    "fre": ["fre", "fra", "french", "francese", "français"],
                    "ger": ["ger", "deu", "german", "tedesco", "deutsch"],
                    "jpn": ["jpn", "japanese", "giapponese"]
                }
                matched = False
                for key, variants in lang_map.items():
                    if lang_filter_lower in variants:
                        if any(v in language for v in variants):
                            matched = True
                            break
                if not matched:
                    continue

        # Nome lingua capitalizzato
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

        # Formato audio
        codec = stream.get("codec", "")
        channels = stream.get("channels")
        title = stream.get("title", "")
        profile = stream.get("profile", "")
        display_title = stream.get("display_title", "") or stream.get("DisplayTitle", "")
        audio_format = _detect_audio_format(codec, channels, title, profile, display_title)

        # Componi stringa
        track_parts = []
        if lang_display:
            track_parts.append(lang_display)
        if audio_format:
            track_parts.append(audio_format)

        if track_parts:
            audio_parts.append(" ".join(track_parts))

    return " · ".join(audio_parts) if audio_parts else ""


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
