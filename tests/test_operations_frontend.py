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


if __name__ == "__main__":
    unittest.main()
