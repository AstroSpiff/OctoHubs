"""Frontend checks for the global operation center."""

from __future__ import annotations

import pathlib
import unittest


class OperationsFrontendTests(unittest.TestCase):
    def test_operation_center_always_renders_operation_timestamps(self):
        source = pathlib.Path("static/operations_center.js").read_text(encoding="utf-8")

        self.assertIn("appendTimeChips(chips, operation);", source)
        self.assertIn("Avvio: ${formatDateTime(startedAt)}", source)
        self.assertIn("Fine: ${formatDateTime(operation.finished_at)}", source)
        self.assertIn("Agg.: ${formatDateTime(operation.updated_at)}", source)
        self.assertNotIn("if (!chips.length && operation.started_at)", source)

    def test_operation_center_reads_json_responses_defensively(self):
        source = pathlib.Path("static/operations_center.js").read_text(encoding="utf-8")

        self.assertIn("async function readOperationJson(response)", source)
        self.assertIn("const payload = await readOperationJson(res);", source)

    def test_operation_center_exposes_wait_for_and_collection_icons(self):
        source = pathlib.Path("static/operations_center.js").read_text(encoding="utf-8")

        self.assertIn("async function waitFor(operationId", source)
        self.assertIn("waitFor,", source)
        self.assertIn("requests_refresh: 'fa-list-check'", source)
        self.assertIn("collections_trakt_lists: 'fa-list-ul'", source)
        self.assertIn("collections_mdblist_lists: 'fa-list-ul'", source)
        self.assertNotIn("const payload = await res.json();", source)
        self.assertIn("console.warn('[OPERATIONS] Refresh unavailable:',", source)
        self.assertNotIn("console.error('[OPERATIONS] Refresh failed:',", source)


if __name__ == "__main__":
    unittest.main()
