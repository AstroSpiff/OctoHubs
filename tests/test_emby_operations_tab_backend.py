import json
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from core.emby_servers import (
    EMBY_SERVER_DISABLED_MESSAGE,
    _emby_server_is_enabled,
    _find_emby_server_by_id,
    _find_emby_server_with_index,
)
from emby_actions.routes import (
    _api_action_targets,
    emby_action_api,
    init_emby_action_routes,
)
from fastapi import HTTPException

from emby_runtime.routes import emby_server_status_api, emby_stop_task_api, init_emby_runtime_routes
from emby_runtime.snapshots import _build_emby_server_status_snapshot, _build_emby_status_stream_payload


class EmbyOperationsTabBackendTests(unittest.TestCase):
    def setUp(self):
        self.flash_messages = []
        init_emby_action_routes(
            require_auth=lambda request: True,
            validate_csrf=lambda request, token: True,
            flash=lambda request, message: self.flash_messages.append(message),
            ensure_db_backend=lambda: None,
            load_config=lambda: None,
        )
        init_emby_runtime_routes(
            require_auth=lambda request: True,
            validate_csrf=lambda request, token: token == "ok",
        )

    def test_stop_task_api_requires_a_valid_csrf_token(self):
        import asyncio

        async def body():
            return {"server_id": "green", "task_id": "task-1"}

        request = SimpleNamespace(headers={"X-CSRF-Token": "invalid"}, json=body)

        with self.assertRaises(HTTPException) as raised:
            asyncio.run(emby_stop_task_api(request))

        self.assertEqual(403, raised.exception.status_code)

    @patch("emby_runtime.snapshots._fetch_emby_active_sessions", return_value=([], None))
    @patch("emby_runtime.snapshots._fetch_emby_scheduled_tasks", return_value=([], None))
    @patch("emby_runtime.snapshots._fetch_emby_status", return_value={"ok": True, "version": "test"})
    @patch(
        "emby_runtime.snapshots.load_config",
        return_value=({"EMBY": {"SERVERS": [{"id": "disabled-server", "enabled": False}]}}, True),
    )
    def test_server_status_snapshot_does_not_probe_disabled_servers(
        self,
        _load_config,
        fetch_status,
        fetch_tasks,
        fetch_streams,
    ):
        payload, status_code = _build_emby_server_status_snapshot("disabled-server")

        self.assertEqual(200, status_code)
        self.assertTrue(payload["success"])
        self.assertEqual({"ok": False, "error": "Server disabilitato"}, payload["status"])
        self.assertEqual([], payload["running_tasks"])
        self.assertIsNone(payload["tasks_error"])
        self.assertEqual([], payload["streams"])
        self.assertIsNone(payload["streams_error"])
        fetch_status.assert_not_called()
        fetch_tasks.assert_not_called()
        fetch_streams.assert_not_called()

    @patch("emby_runtime.snapshots._fetch_active_streams_shared", return_value=([], None))
    @patch("emby_runtime.snapshots._fetch_emby_scheduled_tasks", return_value=([{"Name": "Scan", "is_running": True}], None))
    @patch("emby_runtime.snapshots._fetch_emby_status", return_value={"ok": True, "version": "4.8.0"})
    @patch(
        "emby_runtime.snapshots.load_config",
        return_value=({"EMBY": {"SERVERS": [{"id": "green", "alias": "Green", "enabled": True}]}}, True),
    )
    def test_server_status_api_exposes_the_shared_snapshot(
        self,
        _load_config,
        _fetch_status,
        _fetch_tasks,
        _fetch_streams,
    ):
        import asyncio

        response = asyncio.run(emby_server_status_api("green", object()))
        payload = json.loads(response.body.decode("utf-8"))

        self.assertEqual(200, response.status_code)
        self.assertTrue(payload["success"])
        self.assertEqual({"ok": True, "version": "4.8.0"}, payload["status"])
        self.assertEqual([{"Name": "Scan", "is_running": True}], payload["running_tasks"])
        self.assertEqual([], payload["streams"])

    def test_shared_server_helpers_find_servers_and_normalize_enabled_state(self):
        servers = [
            {"id": "one", "enabled": True},
            {"id": "two", "enabled": False},
        ]

        self.assertEqual("Server disabilitato", EMBY_SERVER_DISABLED_MESSAGE)
        self.assertEqual(servers[0], _find_emby_server_by_id(servers, "one"))
        self.assertEqual((1, servers[1]), _find_emby_server_with_index(servers, "two"))
        self.assertIsNone(_find_emby_server_by_id(servers, "missing"))
        self.assertEqual((None, None), _find_emby_server_with_index(servers, "missing"))
        self.assertTrue(_emby_server_is_enabled(servers[0]))
        self.assertFalse(_emby_server_is_enabled(servers[1]))
        self.assertFalse(_emby_server_is_enabled(None))

    @patch(
        "emby_actions.routes._load_emby_settings_from_db",
        return_value={
            "SERVERS": [
                {
                    "id": "green",
                    "alias": "Green",
                    "url": "https://green.example.test",
                    "icon": "fa-film",
                    "icon_style": "regular",
                    "icon_color": "#8B5CF6",
                    "enabled": True,
                },
                {"id": "disabled", "enabled": False},
            ]
        },
    )
    def test_action_targets_keep_the_configured_server_identity(self, _load_settings):
        self.assertEqual(
            [
                {
                    "id": "green",
                    "name": "Green",
                    "url": "https://green.example.test",
                    "icon": "fa-film",
                    "icon_style": "regular",
                    "icon_color": "#8B5CF6",
                }
            ],
            _api_action_targets(),
        )

    @patch("emby_runtime.snapshots.get_probe_manager")
    @patch("emby_runtime.snapshots._fetch_active_streams_shared", return_value=([], None))
    @patch("emby_runtime.snapshots._fetch_emby_scheduled_tasks", return_value=([], None))
    @patch("emby_runtime.snapshots._fetch_emby_status", return_value={"ok": True, "version": "4.8.0"})
    @patch(
        "emby_runtime.snapshots.load_config",
        return_value=({"EMBY": {"SERVERS": [{"id": "green", "alias": "Green", "enabled": True}]}}, True),
    )
    def test_status_stream_includes_safe_configured_server_identity(
        self,
        _load_config,
        _fetch_status,
        _fetch_tasks,
        _fetch_streams,
        probe_manager,
    ):
        probe_manager.return_value.get_status.return_value = None

        payload = _build_emby_status_stream_payload()

        self.assertTrue(payload["success"])
        self.assertEqual(
            {
                "id": "green",
                "name": "Green",
                "enabled": True,
                "icon": "fa-server",
                "icon_color": "#3b82f6",
                "icon_style": "solid",
            },
            payload["servers"]["green"]["server"],
        )

    @patch("emby_runtime.snapshots.get_probe_manager")
    @patch("emby_runtime.snapshots._fetch_active_streams_shared", return_value=([], None))
    @patch("emby_runtime.snapshots._fetch_emby_scheduled_tasks", return_value=([], None))
    @patch("emby_runtime.snapshots._fetch_emby_status", return_value={"ok": True, "version": "4.8.0"})
    @patch(
        "emby_runtime.snapshots.load_config",
        return_value=({"EMBY": {"SERVERS": [{
            "id": "purple",
            "alias": "Purple",
            "enabled": True,
            "icon": "fa-film",
            "icon_color": "#8B5CF6",
            "icon_style": "regular",
        }]}}, True),
    )
    def test_status_stream_includes_configured_server_icon(
        self,
        _load_config,
        _fetch_status,
        _fetch_tasks,
        _fetch_streams,
        probe_manager,
    ):
        probe_manager.return_value.get_status.return_value = None

        payload = _build_emby_status_stream_payload()

        self.assertEqual("fa-film", payload["servers"]["purple"]["server"]["icon"])
        self.assertEqual("#8B5CF6", payload["servers"]["purple"]["server"]["icon_color"])
        self.assertEqual("regular", payload["servers"]["purple"]["server"]["icon_style"])

    @patch("emby_runtime.snapshots._stop_emby_task", return_value=(True, {}))
    @patch(
        "emby_runtime.snapshots.load_config",
        return_value=({"EMBY": {"SERVERS": [{"id": "disabled-server", "enabled": False}]}}, True),
    )
    def test_stop_task_snapshot_rejects_disabled_servers(self, _load_config, stop_task):
        payload, status_code = _build_emby_server_status_snapshot("missing-server")
        self.assertEqual(404, status_code)
        self.assertFalse(payload["success"])

        from emby_runtime.snapshots import _build_emby_stop_task_snapshot

        payload, status_code = _build_emby_stop_task_snapshot({
            "server_id": "disabled-server",
            "task_id": "task-1",
        })

        self.assertEqual(400, status_code)
        self.assertFalse(payload["success"])
        self.assertEqual("Server disabilitato", payload["message"])
        stop_task.assert_not_called()

    @patch(
        "emby_actions.routes._load_emby_settings_from_db",
        return_value={"SERVERS": [{"id": "disabled-server", "enabled": False}]},
    )
    def test_json_action_rejects_disabled_servers(
        self,
        _load_settings,
    ):
        import asyncio

        async def body():
            return {"action": "restart_server", "server_id": "disabled-server"}

        request = SimpleNamespace(headers={"X-CSRF-Token": "ok"}, json=body)
        response = asyncio.run(emby_action_api(request))
        payload = json.loads(response.body.decode("utf-8"))

        self.assertEqual(404, response.status_code)
        self.assertFalse(payload["success"])
        self.assertIn("Server Emby non trovato o disabilitato", payload["message"])

    @patch("emby_actions.routes._normalize_emby_server", side_effect=lambda server: server)
    @patch("emby_actions.routes._save_emby_settings_to_db")
    @patch("emby_actions.routes._execute_emby_action", return_value=(True, {}))
    @patch(
        "emby_actions.routes._load_emby_settings_from_db",
        return_value={"SERVERS": [{"id": "green", "name": "Green", "enabled": True}]},
    )
    def test_json_library_action_uses_enabled_selected_server(
        self,
        _load_settings,
        execute_action,
        save_settings,
        _normalize,
    ):
        import asyncio

        async def body():
            return {"action": "refresh_libraries", "server_id": "green"}

        request = SimpleNamespace(headers={"X-CSRF-Token": "ok"}, json=body)
        response = asyncio.run(emby_action_api(request))
        payload = json.loads(response.body.decode("utf-8"))

        self.assertEqual(200, response.status_code)
        self.assertTrue(payload["success"])
        self.assertEqual("green", payload["results"][0]["server_id"])
        execute_action.assert_called_once()
        executed_server, executed_action = execute_action.call_args.args
        self.assertEqual("green", executed_server["id"])
        self.assertEqual("refresh_libraries", executed_action)
        self.assertEqual("OK", executed_server["last_action"]["result"])
        save_settings.assert_called_once()

    @patch("emby_actions.routes._normalize_emby_server", side_effect=lambda server: server)
    @patch("emby_actions.routes._save_emby_settings_to_db")
    @patch("emby_actions.routes._execute_emby_action", return_value=(True, {}))
    @patch(
        "emby_actions.routes._load_emby_settings_from_db",
        return_value={"SERVERS": [{"id": "green", "name": "Green", "enabled": True}]},
    )
    def test_json_restart_action_reuses_the_safe_action_endpoint(
        self,
        _load_settings,
        execute_action,
        save_settings,
        _normalize,
    ):
        import asyncio

        async def body():
            return {"action": "restart_server", "server_id": "green"}

        request = SimpleNamespace(headers={"X-CSRF-Token": "ok"}, json=body)
        response = asyncio.run(emby_action_api(request))
        payload = json.loads(response.body.decode("utf-8"))

        self.assertEqual(200, response.status_code)
        self.assertTrue(payload["success"])
        self.assertEqual("green", payload["results"][0]["server_id"])
        self.assertEqual("restart_server", execute_action.call_args.args[1])
        save_settings.assert_called_once()


if __name__ == "__main__":
    unittest.main()
