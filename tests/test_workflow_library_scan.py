"""Workflow scan scopes for the React libraries workspace."""

from __future__ import annotations

import unittest
from unittest.mock import patch

from services import workflows


class WorkflowLibraryScanTests(unittest.TestCase):
    def test_server_scoped_workflow_scans_only_the_requested_server(self):
        config = {
            "EMBY": {
                "SERVERS": [
                    {"id": "server-a", "enabled": True},
                    {"id": "server-b", "enabled": True},
                ]
            }
        }
        submitted = []

        def fetch_libraries(server, _path, method):
            self.assertEqual("GET", method)
            return True, [{"ItemId": f"library-{server['id']}"}]

        def start_scan(payload):
            submitted.append(payload)
            return {"success": True, "job_ids": ["job-1"]}, 200

        context = {"server_id": "server-b"}
        with patch("services.workflows.load_config", return_value=(config, True)), patch(
            "services.workflows._call_emby_api", side_effect=fetch_libraries
        ), patch(
            "emby_libraries.scan_snapshots._build_scan_group_tracked_snapshot",
            side_effect=start_scan,
        ):
            self.assertTrue(workflows._wf_trigger_scan(context))

        self.assertEqual(
            [{"server_id": "server-b", "library_id": "library-server-b"}],
            submitted[0]["libraries"],
        )
        self.assertEqual(["job-1"], context["workflow_job_ids"])

    def test_library_scoped_workflow_keeps_only_the_requested_library(self):
        config = {"EMBY": {"SERVERS": [{"id": "server-a", "enabled": True}]}}
        submitted = []

        with patch("services.workflows.load_config", return_value=(config, True)), patch(
            "services.workflows._call_emby_api",
            return_value=(True, [{"ItemId": "one"}, {"ItemId": "two"}]),
        ), patch(
            "emby_libraries.scan_snapshots._build_scan_group_tracked_snapshot",
            side_effect=lambda payload: (submitted.append(payload) or {"success": True, "job_ids": []}, 200),
        ):
            self.assertTrue(
                workflows._wf_trigger_scan(
                    {"server_id": "server-a", "library_id": "two"}
                )
            )

        self.assertEqual(
            [{"server_id": "server-a", "library_id": "two"}],
            submitted[0]["libraries"],
        )
