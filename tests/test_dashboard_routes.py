"""Compatibility behavior for retired dashboard URLs."""

from __future__ import annotations

import unittest
import threading
from types import SimpleNamespace

from web.dashboard_routes import dashboard_alias, dashboard_root, init_dashboard_routes


class _Request:
    query_params = {}
    url = SimpleNamespace(query="")


class DashboardRouteTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        init_dashboard_routes(
            get_current_user_id=lambda _request: 1,
            has_users=lambda: True,
        )

    async def test_dashboard_redirects_to_research(self):
        response = await dashboard_alias(_Request())

        self.assertEqual(303, response.status_code)
        self.assertEqual("/app/research", response.headers["location"])

    async def test_root_opens_the_react_workspace_for_an_authenticated_user(self):
        response = await dashboard_root(_Request())

        self.assertEqual(303, response.status_code)
        self.assertEqual("/app/emby-live", response.headers["location"])

    async def test_anonymous_user_lookup_runs_outside_the_event_loop_thread(self):
        caller_thread = threading.get_ident()
        worker_threads = []
        init_dashboard_routes(
            get_current_user_id=lambda _request: None,
            has_users=lambda: worker_threads.append(threading.get_ident()) or True,
        )

        response = await dashboard_root(_Request())

        self.assertEqual(303, response.status_code)
        self.assertEqual("/login", response.headers["location"])
        self.assertTrue(worker_threads)
        self.assertNotEqual(caller_thread, worker_threads[0])


if __name__ == "__main__":
    unittest.main()
