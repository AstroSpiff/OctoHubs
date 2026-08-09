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

    def test_last_summary_expansion_finds_details_row_by_row_key(self):
        source = pathlib.Path("static/script.js").read_text(encoding="utf-8")

        self.assertIn("function findDetailsRowForResult(row)", source)
        self.assertIn("const key = getResultDetailKey(row);", source)
        self.assertIn("tbody.querySelectorAll('.details-row')", source)
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

    def test_last_summary_table_has_non_overlapping_layout_contracts(self):
        macros = pathlib.Path("templates/macros.html").read_text(encoding="utf-8")
        css = pathlib.Path("static/dashboard.css").read_text(encoding="utf-8")

        self.assertIn('class="results-table-wrap"', macros)
        self.assertIn('class="result-row-actions"', macros)
        self.assertIn('aria-label="Rimuovi questo risultato dal riepilogo"', macros)
        self.assertIn(".results-table-wrap", css)
        self.assertIn(".result-row-actions", css)
        self.assertIn(".result-summary", css)
        self.assertIn(".result-cleanup-btn", css)

    def test_generic_modal_uses_dedicated_stable_search_styles(self):
        shared_utils = pathlib.Path("static/shared-utils.js").read_text(encoding="utf-8")
        css = pathlib.Path("static/dashboard.css").read_text(encoding="utf-8")

        self.assertIn("generic-modal-content", shared_utils)
        self.assertIn("var(--bg-card, #ffffff)", shared_utils)
        self.assertIn(".generic-modal-content", css)
        self.assertIn(".generic-modal-actions", css)

    def test_requests_list_uses_compact_media_cards_with_external_links(self):
        dashboard = pathlib.Path("templates/dashboard.html").read_text(encoding="utf-8")
        css = pathlib.Path("static/dashboard.css").read_text(encoding="utf-8")
        script = pathlib.Path("static/script.js").read_text(encoding="utf-8")

        self.assertIn("request-poster", dashboard)
        self.assertIn("request-external-links", dashboard)
        self.assertIn("request-links-row", dashboard)
        self.assertIn("req.jellyseerr_url", dashboard)
        self.assertIn("req.trakt_url", dashboard)
        self.assertIn("req.tmdb_url", dashboard)
        self.assertIn("<details class=\"request-rules-details\" open>", dashboard)
        self.assertIn(".request-poster", css)
        self.assertIn(".request-external-links", css)
        self.assertIn(".request-rules-details", css)
        self.assertIn("grid-template-columns: minmax(0, 1fr) minmax(360px, 1fr)", css)
        self.assertIn("const requestRulesCompactQuery = window.matchMedia('(max-width: 1100px)');", script)

    def test_requests_refresh_ui_has_inflight_guard_and_specific_errors(self):
        source = pathlib.Path("static/script.js").read_text(encoding="utf-8")

        self.assertIn("let requestsRefreshInFlight = false;", source)
        self.assertIn("if (requestsRefreshInFlight)", source)
        self.assertIn("'/api/refresh-requests?background=1'", source)
        self.assertIn("window.octohubsOperations?.notifyStarted?.();", source)
        self.assertIn("throw new Error(data.message || 'Errore durante l\\'aggiornamento');", source)
        self.assertIn("const message = err.message || 'Errore durante l\\'aggiornamento';", source)
