import pathlib
import unittest


class EmbyOperationsTabFrontendTests(unittest.TestCase):
    def test_live_task_and_stream_markup_escapes_emby_values(self):
        source = pathlib.Path("static/emby_operations.js").read_text(encoding="utf-8")

        for marker in (
            "const safeName = escapeHtml(name);",
            "const safeState = escapeHtml(state);",
            "const safeTaskId = escapeHtml(taskId);",
            "const safeServerId = escapeHtml(serverId);",
            "const safeUser = escapeHtml(user);",
            "const safeDisplayTitle = escapeHtml(displayTitle);",
            "const safeDevice = escapeHtml(entry.device || 'N/D');",
            "const safeState = escapeHtml(entry.state || 'N/D');",
        ):
            self.assertIn(marker, source)

    def test_disabled_servers_have_explicit_status_and_disabled_restart_button(self):
        js_source = pathlib.Path("static/emby_operations.js").read_text(encoding="utf-8")
        template_source = pathlib.Path("templates/partials/emby_operations.html").read_text(encoding="utf-8")
        css_source = pathlib.Path("static/emby.css").read_text(encoding="utf-8")

        self.assertIn("const updateStatusPill = (pill, status = {}) => {", js_source)
        self.assertIn("status.error === 'Server disabilitato'", js_source)
        self.assertIn("pill.classList.toggle('disabled', isDisabled);", js_source)
        self.assertIn('class="status-pill disabled"', template_source)
        self.assertIn('disabled aria-disabled="true"', template_source)
        self.assertIn(".status-pill.disabled", css_source)

    def test_operations_tab_is_split_into_partial_and_dedicated_script(self):
        dashboard_source = pathlib.Path("templates/emby_dashboard.html").read_text(encoding="utf-8")
        partial_source = pathlib.Path("templates/partials/emby_operations.html").read_text(encoding="utf-8")
        widgets_source = pathlib.Path("static/emby_widgets.js").read_text(encoding="utf-8")
        operations_source = pathlib.Path("static/emby_operations.js").read_text(encoding="utf-8")

        self.assertIn('{% include "partials/emby_operations.html" %}', dashboard_source)
        self.assertIn('data-tab-panel="actions"', partial_source)
        self.assertIn("emby_operations.js", dashboard_source)
        self.assertIn("window.octohubEmbyOperations", operations_source)
        self.assertIn("window.updateStreamPanel = updateStreamPanel;", operations_source)
        self.assertNotIn("startStatusStream", widgets_source)
        self.assertNotIn("button[data-action=\"stop-task\"]", widgets_source)


if __name__ == "__main__":
    unittest.main()
