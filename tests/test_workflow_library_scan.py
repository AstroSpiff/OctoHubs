"""Workflow scan scopes for the React libraries workspace."""

from __future__ import annotations

import unittest
from types import SimpleNamespace
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

        def fetch_libraries(server):
            return [{"id": f"library-{server['id']}"}], None

        def start_scan(payload):
            submitted.append(payload)
            return {"success": True, "job_ids": ["job-1"]}, 200

        context = {"server_id": "server-b"}
        with patch("services.workflows.load_config", return_value=(config, True)), patch(
            "services.workflow_scan_inventory._fetch_emby_libraries",
            side_effect=fetch_libraries,
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
            "services.workflow_scan_inventory._fetch_emby_libraries",
            return_value=([{"id": "one"}, {"id": "two"}], None),
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

    def test_workflow_discovery_uses_the_same_canonical_inventory_as_validation(self):
        """A server-only virtual folder must not reject every scan target."""
        config = {"EMBY": {"SERVERS": [{"id": "server-a", "enabled": True}]}}
        canonical_libraries = [
            {"id": f"library-{index}", "view_ids": [f"view-{index}"]}
            for index in range(12)
        ]
        submitted = []

        def validate_and_start(payload):
            from emby_libraries.scan_manager import EmbyLibraryScanManager

            manager = EmbyLibraryScanManager(
                load_config=lambda: (config, True),
                json_error=lambda message, status_code=400, **extra: (
                    {"success": False, "message": message, **extra},
                    status_code,
                ),
                json_success=lambda message=None, status_code=200, **extra: (
                    {"success": True, "message": message, **extra},
                    status_code,
                ),
                scan_tracker=SimpleNamespace(),
                trigger_library_scan=lambda *_args: (True, {}),
                fetch_libraries=lambda _server: (canonical_libraries, None),
                get_app_event_loop=lambda: None,
                emby_api_client_cls=object,
                log_flush=lambda _message: None,
            )
            submitted_ids = [entry["library_id"] for entry in payload["libraries"]]
            verified, message, status = manager._verify_library_inventory(
                config["EMBY"]["SERVERS"][0],
                submitted_ids,
            )
            self.assertTrue(verified, message)
            self.assertEqual(200, status)
            self.assertEqual(
                {library["id"] for library in canonical_libraries},
                set(submitted_ids),
            )
            self.assertNotIn("server-only-virtual-folder", submitted_ids)
            submitted.append(payload)
            return {"success": True, "job_ids": ["job-canonical"]}, 200

        context = {}
        with patch("services.workflows.load_config", return_value=(config, True)), patch(
            "services.workflow_scan_inventory._fetch_emby_libraries",
            return_value=(canonical_libraries, None),
        ), patch(
            "emby_libraries.scan_snapshots._build_scan_group_tracked_snapshot",
            side_effect=validate_and_start,
        ):
            self.assertTrue(workflows._wf_trigger_scan(context))

        self.assertEqual(12, len(submitted[0]["libraries"]))
        self.assertEqual(["job-canonical"], context["workflow_job_ids"])

    def test_library_scope_accepts_a_current_view_alias_and_scans_canonical_id(self):
        config = {"EMBY": {"SERVERS": [{"id": "server-a", "enabled": True}]}}
        submitted = []

        with patch("services.workflows.load_config", return_value=(config, True)), patch(
            "services.workflow_scan_inventory._fetch_emby_libraries",
            return_value=([{"id": "folder-a", "view_ids": ["requested-view"]}], None),
        ), patch(
            "emby_libraries.scan_snapshots._build_scan_group_tracked_snapshot",
            side_effect=lambda payload: (
                submitted.append(payload) or {"success": True, "job_ids": ["job-1"]},
                200,
            ),
        ):
            self.assertTrue(
                workflows._wf_trigger_scan(
                    {"server_id": "server-a", "library_id": "requested-view"}
                )
            )

        self.assertEqual(
            [{"server_id": "server-a", "library_id": "folder-a"}],
            submitted[0]["libraries"],
        )

    def test_global_workflow_continues_when_one_server_inventory_is_unavailable(self):
        config = {
            "EMBY": {
                "SERVERS": [
                    {"id": "unavailable", "enabled": True},
                    {"id": "available", "enabled": True},
                ]
            }
        }
        submitted = []

        def fetch_libraries(server):
            if server["id"] == "unavailable":
                return [], "Errore richiesta Emby"
            return [{"id": "movies"}], None

        with patch("services.workflows.load_config", return_value=(config, True)), patch(
            "services.workflow_scan_inventory._fetch_emby_libraries",
            side_effect=fetch_libraries,
        ), patch(
            "emby_libraries.scan_snapshots._build_scan_group_tracked_snapshot",
            side_effect=lambda payload: (
                submitted.append(payload) or {"success": True, "job_ids": ["job-1"]},
                200,
            ),
        ):
            self.assertTrue(workflows._wf_trigger_scan({}))

        self.assertEqual(
            [{"server_id": "available", "library_id": "movies"}],
            submitted[0]["libraries"],
        )

    def test_inventory_failure_sets_a_bounded_operator_diagnostic(self):
        config = {"EMBY": {"SERVERS": [{"id": "server-a", "enabled": True}]}}
        context = {}

        with patch("services.workflows.load_config", return_value=(config, True)), patch(
            "services.workflow_scan_inventory._fetch_emby_libraries",
            return_value=([], "SECRET-UPSTREAM-DIAGNOSTIC"),
        ):
            self.assertFalse(workflows._wf_trigger_scan(context))

        self.assertEqual(
            "Impossibile leggere gli inventari librerie dai server Emby",
            context["_workflow_scan_error"],
        )
        self.assertNotIn("SECRET-UPSTREAM-DIAGNOSTIC", str(context))
