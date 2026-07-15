import unittest
from unittest.mock import patch

from core.emby_servers import (
    EMBY_SERVER_DISABLED_MESSAGE,
    _emby_server_is_enabled,
    _find_emby_server_by_id,
    _find_emby_server_with_index,
)
from emby_actions.routes import emby_action_post, init_emby_action_routes
from emby_runtime.snapshots import _build_emby_server_status_snapshot


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

    @patch("emby_actions.routes._save_emby_settings_to_db")
    @patch("emby_actions.routes._execute_emby_action", return_value=(True, {}))
    @patch(
        "emby_actions.routes._load_emby_settings_from_db",
        return_value={"SERVERS": [{"id": "disabled-server", "enabled": False}]},
    )
    def test_single_action_rejects_disabled_servers(
        self,
        _load_settings,
        execute_action,
        save_settings,
    ):
        import asyncio

        response = asyncio.run(emby_action_post(
            request=object(),
            server_id="disabled-server",
            action="restart_server",
            csrf_token="ok",
        ))

        self.assertEqual(303, response.status_code)
        self.assertIn("Server Emby disabilitato.", self.flash_messages)
        execute_action.assert_not_called()
        save_settings.assert_not_called()


if __name__ == "__main__":
    unittest.main()
