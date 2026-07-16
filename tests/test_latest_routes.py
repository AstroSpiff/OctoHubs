"""Latest publications route behavior."""

from __future__ import annotations

import json
import unittest
from unittest.mock import patch

from emby_latest.routes import (
    emby_latest_enrich,
    emby_latest_notify,
    emby_latest_preview,
    emby_latest_refresh,
    init_emby_latest_routes,
)


class _BadJsonRequest:
    query_params = {}

    async def json(self):
        raise ValueError("bad json")


class _JsonRequest:
    query_params = {}

    def __init__(self, body=None):
        self._body = body if body is not None else {}

    async def json(self):
        return self._body


class LatestRouteTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        init_emby_latest_routes(
            require_auth=lambda request: True,
            validate_csrf=lambda request, token: True,
        )

    async def test_json_post_routes_reject_invalid_json_without_calling_handlers(self):
        cases = (
            (emby_latest_preview, "emby_latest.api_handlers.build_preview_snapshot"),
            (emby_latest_enrich, "emby_latest.api_handlers.build_enrich_snapshot"),
            (emby_latest_notify, "emby_latest.api_handlers.build_notify_snapshot"),
        )

        for route_func, handler_path in cases:
            with self.subTest(route=route_func.__name__), patch(handler_path) as handler:
                handler.return_value = ({"success": True}, 200)
                response = await route_func(_BadJsonRequest())

            self.assertEqual(400, response.status_code)
            self.assertEqual(
                {"success": False, "message": "Body non valido"},
                json.loads(response.body),
            )
            handler.assert_not_called()

    async def test_post_routes_reject_invalid_csrf_without_calling_handlers(self):
        init_emby_latest_routes(
            require_auth=lambda request: True,
            validate_csrf=lambda request, token: False,
        )

        cases = (
            (
                emby_latest_refresh,
                "emby_latest.api_handlers.build_latest_refresh_payload",
                _JsonRequest(),
                (),
            ),
            (
                emby_latest_preview,
                "emby_latest.api_handlers.build_preview_snapshot",
                _JsonRequest({"template": "{title}", "items": {}}),
                (),
            ),
            (
                emby_latest_enrich,
                "emby_latest.api_handlers.build_enrich_snapshot",
                _JsonRequest({"item": {"title": "Movie"}}),
                (),
            ),
            (
                emby_latest_notify,
                "emby_latest.api_handlers.build_notify_snapshot",
                _JsonRequest({"per_server_limit": 1}),
                (),
            ),
        )

        for route_func, handler_path, request, args in cases:
            with self.subTest(route=route_func.__name__), patch(handler_path) as handler:
                handler.return_value = ({"success": True}, 200)
                response = await route_func(request, *args)

            self.assertEqual(403, response.status_code)
            self.assertEqual(
                {"success": False, "message": "CSRF token non valido"},
                json.loads(response.body),
            )
            handler.assert_not_called()


if __name__ == "__main__":
    unittest.main()
