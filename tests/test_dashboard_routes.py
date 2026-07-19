"""Dashboard request filtering behavior."""

from __future__ import annotations

import unittest
from unittest.mock import patch

from web.dashboard_routes import dashboard_root, init_dashboard_routes


class _Templates:
    def TemplateResponse(self, request, name, context):
        return {"template": name, "context": context}


class _Request:
    query_params = {}


class DashboardRouteTests(unittest.IsolatedAsyncioTestCase):
    async def test_dashboard_hides_normalized_available_requests_and_results(self):
        init_dashboard_routes(
            templates=_Templates(),
            get_flash_messages=lambda _request: [],
            get_csrf_token=lambda _request: "csrf",
            get_current_user_id=lambda _request: 1,
            has_users=lambda: True,
        )
        cached_overview = [
            {
                "id": 436,
                "title": "Widow's Bay",
                "media_type": "tv",
                "status": 4,
                "is_available": False,
                "season_status": [{"season": 1, "status": "available"}],
            },
            {
                "id": 451,
                "title": "CIA",
                "media_type": "tv",
                "status": 4,
                "is_available": False,
                "season_status": [{"season": 1, "status": "pending"}],
            },
        ]
        last_results = {
            "items": [
                {"request_id": 436, "title": "Widow's Bay"},
                {"request_id": 451, "title": "CIA"},
            ]
        }

        with patch("web.dashboard_routes.load_config", return_value=({"SEARCH_RULES": {}}, True)), patch(
            "web.dashboard_routes.scan_manager.get_status",
            return_value={"last_summary": last_results},
        ), patch(
            "web.dashboard_routes._load_cached_requests_overview",
            return_value=(cached_overview, None),
        ), patch(
            "web.dashboard_routes._get_total_blacklist_counts",
            return_value=(0, 0),
        ):
            response = await dashboard_root(_Request())

        context = response["context"]
        self.assertEqual([req["id"] for req in context["requests_overview"]], [451])
        self.assertEqual([item["request_id"] for item in context["results"]["items"]], [451])


if __name__ == "__main__":
    unittest.main()
