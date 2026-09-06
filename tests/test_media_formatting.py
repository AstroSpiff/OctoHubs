"""Regression coverage for the canonical Emby media formatter."""

from emby_latest import media as latest_media
from emby_runtime import media_utils as runtime_media
from emby_runtime.media_formatting import _detect_audio_format


def test_dts_hd_aliases_have_one_canonical_result():
    cases = (
        ("DTSHDMA", 8, "", "", ""),
        ("dts", 8, "DTS-HD Master Audio", "", ""),
        ("dts-hd ma", 6, "", "", ""),
    )

    assert [_detect_audio_format(*case) for case in cases] == [
        "DTS-HD MA 7.1",
        "DTS-HD MA 7.1",
        "DTS-HD MA 5.1",
    ]


def test_latest_and_runtime_export_the_same_formatter():
    streams = [
        {"type": "video", "codec": "hevc", "hdr_type": "HDR10PLUS"},
        {
            "type": "audio",
            "codec": "dts",
            "channels": 8,
            "language": "ita",
            "title": "DTS-HD Master Audio",
        },
    ]

    assert latest_media._format_video_details(streams) == runtime_media._format_video_details(streams)
    assert latest_media._format_audio_details(streams) == runtime_media._format_audio_details(streams)
    assert latest_media._format_audio_details(streams) == "Italiano DTS-HD MA 7.1"
