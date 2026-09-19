"""Global operation center routes."""

from __future__ import annotations

import unittest
from unittest.mock import patch

from core.storage import StorageError
from services.operations_routes import (
    api_operations,
    api_operations_clear_completed,
    init_operations_routes,
    router,
)
from services.operations_api_models import (
    ClearCompletedOperationsResponse,
    OperationsSnapshotResponse,
    OperationsUnavailableResponse,
)
from services.operations_presentation import present_operation_server_names


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
    def test_probe_operation_summaries_use_configured_server_names(self):
        operations = [
            {
                "id": "operation-1",
                "kind": "probe_processing",
                "summary": "db53a209-4328-4e2a-a8e6-4289f15b9379",
                "details": {
                    "server_ids": ["db53a209-4328-4e2a-a8e6-4289f15b9379"]
                },
            }
        ]

        presented = present_operation_server_names(
            operations,
            {"db53a209-4328-4e2a-a8e6-4289f15b9379": "Black"},
        )

        self.assertEqual(presented[0]["summary"], "Black")
        self.assertEqual(
            operations[0]["summary"],
            "db53a209-4328-4e2a-a8e6-4289f15b9379",
        )

    async def test_operations_route_enriches_existing_probe_records(self):
        server_id = "db53a209-4328-4e2a-a8e6-4289f15b9379"

        class Tracker:
            def list_operations(self):
                return [{
                    "id": "operation-1",
                    "kind": "probe_processing",
                    "summary": server_id,
                    "status": "running",
                    "details": {"server_ids": [server_id]},
                }]

        init_operations_routes(
            require_auth=lambda _request: {"id": "admin"},
            validate_csrf=lambda _request, _token: True,
            get_operation_tracker=Tracker,
        )

        with patch(
            "services.operations_routes.get_active_config_snapshot",
            return_value={
                "EMBY": {"SERVERS": [{"id": server_id, "name": "Black"}]}
            },
        ):
            payload = await api_operations(object())

        self.assertEqual(payload["operations"][0]["summary"], "Black")

    def test_operations_routes_publish_their_response_contracts(self):
        routes = {route.path: route for route in router.routes}

        operations_responses = routes["/api/operations"].responses
        assert operations_responses[200]["model"] is OperationsSnapshotResponse
        assert operations_responses[500]["model"] is OperationsUnavailableResponse
        assert operations_responses[503]["model"] is OperationsUnavailableResponse
        assert (
            routes["/api/operations/clear-completed"].responses[200]["model"]
            is ClearCompletedOperationsResponse
        )

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
        self.assertEqual(
            response.body.decode(),
            '{"ok":false,"error":"Centro operazioni temporaneamente non disponibile"}',
        )


if __name__ == "__main__":
    unittest.main()
