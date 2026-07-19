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

    def test_last_summary_expansion_uses_adjacent_details_row(self):
        source = pathlib.Path("static/script.js").read_text(encoding="utf-8")

        self.assertIn("const detailsRow = row.nextElementSibling;", source)
        self.assertIn("detailsRow.classList.contains('details-row')", source)
        self.assertNotIn("document.querySelector(`.details-row[data-details-for=", source)

    def test_last_summary_cleanup_controls_are_available(self):
        dashboard = pathlib.Path("templates/dashboard.html").read_text(encoding="utf-8")
        macros = pathlib.Path("templates/macros.html").read_text(encoding="utf-8")
        script = pathlib.Path("static/script_results.js").read_text(encoding="utf-8")

        self.assertIn('id="cleanup-resolved-results-btn"', dashboard)
        self.assertIn('id="reset-scan-results-btn"', dashboard)
        self.assertIn('data-result-cleanup-single', macros)
        self.assertIn("/api/search/results/cleanup", script)
        self.assertNotIn("cleanup-stale-results-btn", dashboard)
