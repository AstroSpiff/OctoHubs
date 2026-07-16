"""Latest publications MediaInfo state."""

from __future__ import annotations

import unittest

from emby_latest.batch_processor import extract_versions


class LatestMediaInfoTests(unittest.TestCase):
    def test_extract_versions_marks_mediainfo_available_with_runtime_and_video_stream(self):
        versions = extract_versions(
            {
                "RunTimeTicks": 7_200_000_000,
                "MediaSources": [
                    {
                        "Id": "source-a",
                        "Path": "/media/movie.mkv",
                        "RunTimeTicks": 7_200_000_000,
                        "Container": "mkv",
                        "MediaStreams": [
                            {"Type": "Video", "Codec": "hevc", "Width": 3840, "Height": 2160},
                            {"Type": "Audio", "Codec": "aac", "Language": "ita", "Channels": 6},
                        ],
                    }
                ],
            }
        )

        self.assertEqual(1, len(versions))
        self.assertTrue(versions[0]["mediainfo_available"])

    def test_extract_versions_marks_mediainfo_unavailable_without_video_stream(self):
        versions = extract_versions(
            {
                "RunTimeTicks": 7_200_000_000,
                "MediaSources": [
                    {
                        "Id": "source-a",
                        "Path": "/media/movie.mkv",
                        "RunTimeTicks": 7_200_000_000,
                        "MediaStreams": [
                            {"Type": "Audio", "Codec": "aac", "Language": "ita", "Channels": 6},
                        ],
                    }
                ],
            }
        )

        self.assertEqual(1, len(versions))
        self.assertFalse(versions[0]["mediainfo_available"])


if __name__ == "__main__":
    unittest.main()
