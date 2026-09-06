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
from realtime.status_snapshot import (
    invalidate_status_snapshot_cache,
    reset_status_snapshot_cache,
    shared_status_snapshot,
)


class EmbyOperationsTabBackendTests(unittest.TestCase):
    def setUp(self):
        reset_status_snapshot_cache()
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

    @patch("emby_runtime.snapshots._fetch_active_streams_shared", return_value=([], None))
    @patch("emby_runtime.snapshots._fetch_emby_scheduled_tasks", return_value=([], None))
    @patch("emby_runtime.snapshots._fetch_emby_status", return_value={"ok": True})
    @patch(
        "emby_runtime.snapshots.load_config",
        return_value=({"EMBY": {"SERVERS": [{"id": "green", "enabled": True}]}}, True),
    )
    def test_server_status_api_reuses_its_single_flight_cache(
        self,
        _load_config,
        fetch_status,
        fetch_tasks,
        fetch_streams,
    ):
        import asyncio

        async def read_twice():
            first_response = await emby_server_status_api("green", object())
            second_response = await emby_server_status_api("green", object())
            return first_response, second_response

        first, second = asyncio.run(read_twice())

        self.assertEqual(first.body, second.body)
        fetch_status.assert_called_once_with({"id": "green", "enabled": True})
        fetch_tasks.assert_called_once_with({"id": "green", "enabled": True})
        fetch_streams.assert_called_once_with({"id": "green", "enabled": True})

    @patch(
        "emby_runtime.snapshots.load_config",
        return_value=({"EMBY": {"SERVERS": []}}, True),
    )
    def test_unknown_server_status_does_not_allocate_a_cache_key(self, _load_config):
        import asyncio
        from realtime import status_snapshot

        response = asyncio.run(emby_server_status_api("missing", object()))

        self.assertEqual(404, response.status_code)
        self.assertEqual({}, dict(status_snapshot._IN_FLIGHT))
        self.assertNotIn(("server", "missing"), status_snapshot._CACHED_PAYLOADS)

    @patch(
        "emby_runtime.snapshots.load_config",
        return_value=(
            {
                "EMBY": {
                    "SERVERS": [
                        {
                            "id": "green",
                            "enabled": False,
                            "url": "https://user:CANARY_PASSWORD@emby.test?access_token=CANARY_TOKEN",
                        }
                    ]
                }
            },
            True,
        ),
    )
    def test_status_stream_snapshot_redacts_credentials_embedded_in_server_url(self, _load_config):
        payload = _build_emby_status_stream_payload()

        public_url = payload["servers"]["green"]["server"]["url"]
        self.assertNotIn("CANARY_PASSWORD", public_url)
        self.assertNotIn("CANARY_TOKEN", public_url)
        self.assertEqual(
            "https://[REDACTED]@emby.test?access_token=[REDACTED]",
            public_url,
        )

    def test_status_cache_keeps_server_keys_separate_and_supports_tuple_payloads(self):
        import asyncio

        async def read_servers():
            green = await shared_status_snapshot(
                lambda: ({"server": "green"}, 200),
                cache_key=("server", "green"),
            )
            blue = await shared_status_snapshot(
                lambda: ({"server": "blue"}, 404),
                cache_key=("server", "blue"),
            )
            return green, blue

        green, blue = asyncio.run(read_servers())

        self.assertEqual(({"server": "green"}, 200), green)
        self.assertEqual(({"server": "blue"}, 404), blue)

        invalidate_status_snapshot_cache(("server", "green"))

        async def read_after_invalidation():
            green_result = await shared_status_snapshot(
                lambda: ({"server": "green-new"}, 201),
                cache_key=("server", "green"),
            )
            blue_result = await shared_status_snapshot(
                lambda: ({"server": "should-not-replace-blue"}, 500),
                cache_key=("server", "blue"),
            )
            return green_result, blue_result

        green, blue = asyncio.run(read_after_invalidation())
        self.assertEqual(({"server": "green-new"}, 201), green)
        self.assertEqual(({"server": "blue"}, 404), blue)

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

    @patch(
        "emby_actions.routes._load_emby_settings_from_db",
        return_value={
            "SERVERS": [
                {
                    "id": "green",
                    "alias": "Green",
                    "url": "https://viewer:CANARY_PASSWORD@green.example.test/base?token=CANARY_TOKEN&safe=1",
                    "enabled": True,
                }
            ]
        },
    )
    def test_action_targets_redact_only_embedded_url_credentials(self, _load_settings):
        target = _api_action_targets()[0]

        self.assertEqual(
            "https://[REDACTED]@green.example.test/base?token=[REDACTED]&safe=1",
            target["url"],
        )
        self.assertNotIn("CANARY", target["url"])

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
    @patch("emby_actions.routes._mutate_emby_settings_in_db")
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
    @patch("emby_actions.routes._mutate_emby_settings_in_db")
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
