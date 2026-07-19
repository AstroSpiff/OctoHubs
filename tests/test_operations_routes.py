"""Global operation center routes."""

from __future__ import annotations

import unittest

from core.storage import StorageError
from services.operations_routes import (
    api_operations,
    api_operations_clear_completed,
    init_operations_routes,
)


class _Tracker:
    def __init__(self):
        self.cleared = False

    def list_operations(self):
        return [
            {"id": "active", "status": "running"},
            {"id": "done", "status": "success"},
        ]

    def clear_completed(self):
        self.cleared = True
        return 1


class OperationRouteTests(unittest.IsolatedAsyncioTestCase):
    async def test_global_operations_route_returns_operations_and_active_count(self):
        tracker = _Tracker()
        init_operations_routes(
            require_auth=lambda _request: {"id": "admin"},
            validate_csrf=lambda _request, _token: True,
            get_operation_tracker=lambda: tracker,
        )

        payload = await api_operations(object())

        self.assertTrue(payload["ok"])
        self.assertEqual(payload["active_count"], 1)
        self.assertEqual([item["id"] for item in payload["operations"]], ["active", "done"])

    async def test_global_operations_clear_completed_uses_tracker(self):
        tracker = _Tracker()
        init_operations_routes(
            require_auth=lambda _request: {"id": "admin"},
            validate_csrf=lambda _request, _token: True,
            get_operation_tracker=lambda: tracker,
        )

        payload = await api_operations_clear_completed(object())

        self.assertTrue(payload["ok"])
        self.assertEqual(payload["removed"], 1)
        self.assertTrue(tracker.cleared)

    async def test_global_operations_route_returns_json_when_tracker_unavailable(self):
        init_operations_routes(
            require_auth=lambda _request: {"id": "admin"},
            validate_csrf=lambda _request, _token: True,
            get_operation_tracker=lambda: (_ for _ in ()).throw(StorageError("DB non disponibile")),
        )

        response = await api_operations(object())

        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.body.decode(), '{"ok":false,"error":"DB non disponibile"}')


if __name__ == "__main__":
    unittest.main()
