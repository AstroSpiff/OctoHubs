"""Template rendering compatibility tests."""

from __future__ import annotations

import ast
import unittest
from pathlib import Path


ROUTE_FILES = [
    Path("services/setup_routes.py"),
    Path("web/auth_routes.py"),
    Path("web/config_routes.py"),
    Path("web/dashboard_routes.py"),
    Path("web/emby_routes.py"),
    Path("emby_collections/routes.py"),
]


class TemplateResponseCallTests(unittest.TestCase):
    def test_template_response_uses_request_first_signature(self):
        legacy_calls: list[str] = []

        for path in ROUTE_FILES:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                func = node.func
                if not isinstance(func, ast.Attribute) or func.attr != "TemplateResponse":
                    continue
                if node.args and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str):
                    legacy_calls.append(f"{path}:{node.lineno}")

        self.assertEqual([], legacy_calls)


if __name__ == "__main__":
    unittest.main()
