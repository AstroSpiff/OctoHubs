"""Latest publications frontend contracts."""

from __future__ import annotations

import pathlib
import unittest


class LatestFrontendTests(unittest.TestCase):
    def test_verify_data_filters_by_server_id_not_visible_name(self):
        source = pathlib.Path("static/emby_verify.js").read_text(encoding="utf-8")

        self.assertIn("option.value = serverId;", source)
        self.assertIn("item.server_id === serverId", source)
        self.assertIn("window.octohubLatest || {}", source)
        self.assertIn("getLatestFetchLimits", pathlib.Path("static/emby_latest.js").read_text(encoding="utf-8"))
        self.assertNotIn("option.value = serverName;", source)
        self.assertNotIn("m.server_name === serverName", source)
        self.assertNotIn("s.server_name === serverName", source)

    def test_latest_reset_text_does_not_claim_preview_cache_reset(self):
        source = pathlib.Path("templates/emby_dashboard.html").read_text(encoding="utf-8")

        self.assertIn("Reset completo delle pubblicazioni (STATE + CACHE).", source)
        self.assertNotIn("STATE + CACHE + PREVIEW", source)

    def test_latest_notify_sends_per_server_limit(self):
        source = pathlib.Path("static/emby_latest.js").read_text(encoding="utf-8")

        self.assertIn("const limits = getLatestFetchLimits();", source)
        self.assertIn("per_server_limit: limits.perServer", source)

    def test_latest_notify_uses_all_servers_not_visible_tab(self):
        source = pathlib.Path("static/emby_latest.js").read_text(encoding="utf-8")

        self.assertIn("server_id: 'all'", source)
        self.assertNotIn("server_id: latestState.currentServerId || 'all'", source)

    def test_latest_refresh_can_reload_cache_after_initial_load(self):
        source = pathlib.Path("static/emby_latest.js").read_text(encoding="utf-8")

        self.assertIn("latestState.loaded && !force && !allowRefresh && !cacheOnly", source)

    def test_latest_progress_completion_reloads_latest_cache_even_after_reset(self):
        source = pathlib.Path("static/emby_latest.js").read_text(encoding="utf-8")

        self.assertIn(
            "if (!active) {\n"
            "                stopLatestProgressPolling();\n"
            "                loadLatestReleases(false, false, true);\n"
            "            }",
            source,
        )
        self.assertNotIn(
            "if (!active) {\n"
            "                stopLatestProgressPolling();\n"
            "                if (latestState.loaded) {",
            source,
        )

    def test_latest_script_cache_buster_tracks_operations_change(self):
        source = pathlib.Path("templates/emby_dashboard.html").read_text(encoding="utf-8")

        self.assertIn("emby_latest.js') }}?v=20260718-latest-tab-load", source)
        self.assertIn("script_shell.js') }}?v=20260718-main-tab-events", source)

    def test_latest_refresh_notifies_global_operation_center(self):
        source = pathlib.Path("static/emby_latest.js").read_text(encoding="utf-8")
        operations_source = pathlib.Path("static/operations_center.js").read_text(encoding="utf-8")
        template = pathlib.Path("templates/emby_dashboard.html").read_text(encoding="utf-8")

        self.assertIn("window.octohubOperations?.notifyStarted?.();", source)
        self.assertIn("latest_refresh: 'fa-newspaper'", operations_source)
        self.assertIn("operations_center.js') }}?v=20260719-operations-json", template)

    def test_latest_refresh_button_uses_inflight_guard(self):
        source = pathlib.Path("static/emby_latest.js").read_text(encoding="utf-8")

        self.assertIn("refreshing: false", source)
        self.assertIn("if (latestState.refreshing) {", source)
        self.assertIn("latestState.refreshing = true;", source)
        self.assertIn("latestState.refreshing = false;", source)

    def test_latest_refresh_waits_for_progress_when_cache_was_reset(self):
        source = pathlib.Path("static/emby_latest.js").read_text(encoding="utf-8")

        self.assertIn(
            "if (latestState.loaded) {\n"
            "                loadLatestReleases(false, false, true);\n"
            "            }",
            source,
        )
        self.assertNotIn(
            "            loadLatestReleases(false, false, true);\n"
            "            if (data.refreshing) {",
            source,
        )

    def test_latest_tab_does_not_render_redundant_local_progress_loader(self):
        source = pathlib.Path("static/emby_latest.js").read_text(encoding="utf-8")
        template = pathlib.Path("templates/emby_dashboard.html").read_text(encoding="utf-8")

        self.assertNotIn("data-latest-progress", template)
        self.assertNotIn("data-latest-progress-bar", template)
        self.assertNotIn("latestProgressWrap.style.display", source)
        self.assertIn("const updateLatestProgressUI = (progress, refreshing) =>", source)

    def test_latest_load_message_uses_database_language_not_raw_cache_error(self):
        source = pathlib.Path("static/emby_latest.js").read_text(encoding="utf-8")

        self.assertIn("normalizeLatestLoadMessage", source)
        self.assertIn("Aggiornamento Pubblicazioni in corso...", source)
        self.assertIn("Nessun dato Pubblicazioni salvato nel DB. Avvia un aggiornamento.", source)
        self.assertNotIn("renderLatestList([], latestMoviesContainer, latestMoviesCount, message);", source)

    def test_latest_tab_loads_cache_when_it_becomes_active(self):
        shell_source = pathlib.Path("static/script_shell.js").read_text(encoding="utf-8")
        latest_source = pathlib.Path("static/emby_latest.js").read_text(encoding="utf-8")

        self.assertIn("octohub:main-tab-changed", shell_source)
        self.assertIn("detail: { tab: target }", shell_source)
        self.assertIn("octohub:main-tab-changed", latest_source)
        self.assertIn("if (tab === 'latest')", latest_source)
        self.assertIn("if (isLatestTabActive())", latest_source)
        self.assertIn("loadLatestReleases(false, false, true);", latest_source)

    def test_latest_episode_code_does_not_convert_null_to_s00e00(self):
        source = pathlib.Path("static/emby_latest.js").read_text(encoding="utf-8")

        self.assertIn("normalizeEpisodeIndex", source)
        self.assertIn("if (value === null || value === undefined) {", source)
        self.assertIn("allowZero ? number < 0 : number <= 0", source)
        self.assertIn("normalizeEpisodeIndex(seasonNumber, { allowZero: true });", source)
        self.assertIn("normalizeEpisodeIndex(episodeNumber);", source)
        self.assertNotIn("const season = Number(seasonNumber);\n        const episode = Number(episodeNumber);", source)

    def test_latest_fetch_per_server_limit_uses_configured_latest_limits(self):
        source = pathlib.Path("templates/emby_dashboard.html").read_text(encoding="utf-8")

        self.assertIn(
            'data-latest-fetch-per-server="{{ [latest_max_movies, latest_max_series] | max }}"',
            source,
        )
        self.assertNotIn('data-latest-fetch-per-server="100"', source)

    def test_latest_frontend_preview_image_tokens_include_non_poster_images(self):
        source = pathlib.Path("static/emby_latest.js").read_text(encoding="utf-8")

        for token in (
            "image_url",
            "tmdb_poster_url",
            "poster_url",
            "tmdb_backdrop_url",
            "backdrop_url",
            "tmdb_logo_url",
            "logo_url",
            "tmdb_banner_url",
            "banner_url",
            "tmdb_thumb_url",
            "thumb_url",
        ):
            self.assertIn(f"'{token}'", source)

    def test_latest_frontend_preview_does_not_invent_missing_images(self):
        source = pathlib.Path("static/emby_latest.js").read_text(encoding="utf-8")

        self.assertNotIn("imageEnabled && !imageUrl && previewImageFallback", source)
        self.assertNotIn("return previewImageFallback;", source)

    def test_latest_list_escapes_image_urls_in_markup(self):
        source = pathlib.Path("static/emby_latest.js").read_text(encoding="utf-8")

        self.assertIn('src="${escapeHtml(item.image_url)}"', source)
        self.assertNotIn('src="${item.image_url}"', source)

    def test_latest_frontend_has_no_global_notification_settings_ui(self):
        template = pathlib.Path("templates/emby_dashboard.html").read_text(encoding="utf-8")
        script = pathlib.Path("static/emby_latest.js").read_text(encoding="utf-8")

        self.assertNotIn("notification-settings", template)
        self.assertNotIn("latest_active_preset_id", template)
        self.assertNotIn("latest_telegram_presets", template)
        self.assertNotIn("data-latest-active-preset", template)
        self.assertNotIn("data-latest-active-preset", script)

    def test_verify_data_enrich_forces_omdb_refresh(self):
        source = pathlib.Path("static/emby_verify.js").read_text(encoding="utf-8")

        self.assertIn("force_omdb: true", source)

    def test_verify_data_uses_api_message_for_load_errors(self):
        source = pathlib.Path("static/emby_verify.js").read_text(encoding="utf-8")

        self.assertIn("data.error || data.message || 'Errore nel caricamento dei dati'", source)

    def test_verify_data_checks_all_supported_tmdb_image_fields(self):
        source = pathlib.Path("static/emby_verify.js").read_text(encoding="utf-8")

        for field in (
            "tmdb_poster_url",
            "tmdb_backdrop_url",
            "tmdb_logo_url",
            "tmdb_banner_url",
            "tmdb_thumb_url",
        ):
            self.assertIn(f"'{field}'", source)

    def test_verify_data_escapes_rendered_field_values(self):
        source = pathlib.Path("static/emby_verify.js").read_text(encoding="utf-8")

        self.assertIn("${escapeHtml(valueDisplay)}", source)
        self.assertNotIn("${valueDisplay}</div>", source)

    def test_verify_data_skips_absent_audio_languages_when_probe_found_audio(self):
        source = pathlib.Path("static/emby_verify.js").read_text(encoding="utf-8")

        self.assertIn("optionalAudioLanguageFields", source)
        self.assertIn("isAbsentAudioLanguageField(field, source)", source)
        self.assertIn("return hasFieldValue(source.audio_langs) || hasFieldValue(source.audio_details);", source)
        self.assertIn("if (isAbsentAudioLanguageField(field, source)) {", source)
        self.assertIn("return;", source)

    def test_verify_data_skips_missing_file_fields_when_mediainfo_is_verified(self):
        source = pathlib.Path("static/emby_verify.js").read_text(encoding="utf-8")

        self.assertIn("mediaInfoFields", source)
        self.assertIn("source.mediainfo_available", source)
        self.assertIn("source.mediainfo_available === true", source)
        self.assertIn("isVerifiedMediaInfoField(field, source)", source)
        self.assertIn("if (isVerifiedMediaInfoField(field, source)) {", source)

    def test_verify_script_cache_buster_tracks_verify_fields_change(self):
        source = pathlib.Path("templates/emby_dashboard.html").read_text(encoding="utf-8")

        self.assertIn("emby_verify.js') }}?v=20260716-verify-mediainfo-state", source)


if __name__ == "__main__":
    unittest.main()
