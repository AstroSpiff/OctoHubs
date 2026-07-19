"""Search frontend contracts."""

from __future__ import annotations

import pathlib
import unittest


class SearchFrontendTests(unittest.TestCase):
    def test_tmdb_clear_selection_removes_stale_selected_seasons(self):
        source = pathlib.Path("static/script_tmdb_emby.js").read_text(encoding="utf-8")

        self.assertIn("const tmdbSeasonList = document.getElementById('tmdb-season-list');", source)
        self.assertIn("if (tmdbSeasonList) tmdbSeasonList.innerHTML = '';", source)

    def test_tmdb_script_cache_buster_tracks_search_changes(self):
        for template_path in (
            "templates/dashboard.html",
            "templates/emby_dashboard.html",
            "templates/emby_collections.html",
            "templates/configuration.html",
        ):
            with self.subTest(template=template_path):
                source = pathlib.Path(template_path).read_text(encoding="utf-8")

                self.assertIn("script_tmdb_emby.js') }}?v=20260719-search", source)
                self.assertNotIn("script_tmdb_emby.js') }}?v=20260628-tmdb", source)
