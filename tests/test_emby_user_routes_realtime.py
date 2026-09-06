import asyncio
import threading
import time
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import FastAPI

from emby_users.auto_sync_manager import AutoSyncManager
from emby_users.api_models import AccessToggleRequest
from emby_users.icon_api_models import IconBindingRequest
from emby_users.icon_routes import (
    api_emby_icons_binding_save,
    init_emby_icon_routes,
    router as emby_icon_router,
)
from emby_users.routes import (
    USERS_UPDATED_MESSAGE,
    api_emby_users_toggle_remote,
    init_emby_user_routes,
    router as emby_users_router,
)


class EmbyUserRoutesRealtimeTests(unittest.TestCase):
    def test_group_sync_is_single_flight(self):
        manager = object.__new__(AutoSyncManager)
        manager._active_groups = set()
        manager._active_groups_lock = threading.Lock()
        manager._state_tracker = SimpleNamespace(storage=None)
        manager._mark_group_sync_result = lambda *args: True
        entered = threading.Event()
        release = threading.Event()

        def sync_group(_group, operation_id=None):
            entered.set()
            release.wait(1)
            return {"status": "success"}

        manager._sync_group = sync_group
        first_result = []
        worker = threading.Thread(
            target=lambda: first_result.append(
                manager._sync_group_singleflight({"id": "group-1"})
            )
        )
        worker.start()
        self.assertTrue(entered.wait(1))

        second = manager._sync_group_singleflight({"id": "group-1"})
        time.sleep(0.01)
        release.set()
        worker.join(1)

        self.assertEqual(second["reason"], "already_running")
        self.assertEqual(first_result[0]["status"], "success")

    def test_json_request_contracts_are_exposed_in_openapi(self):
        app = FastAPI()
        app.include_router(emby_users_router)
        app.include_router(emby_icon_router)

        schema = app.openapi()
        users_contract = schema["paths"]["/api/emby/users/toggle-remote"]["post"]["requestBody"]
        icons_contract = schema["paths"]["/api/emby/icons/binding"]["post"]["requestBody"]
        upload_contract = schema["paths"]["/api/emby/icons/rule"]["post"]["requestBody"]

        self.assertIn("AccessToggleRequest", str(users_contract))
        self.assertIn("IconBindingRequest", str(icons_contract))
        self.assertIn("multipart/form-data", upload_contract["content"])
        self.assertIn("one_way", str(schema["components"]["schemas"]["GroupSyncSettingsRequest"]))

    def test_icon_binding_update_notifies_open_user_views(self):
        manager = SimpleNamespace(
            icon_manager=SimpleNamespace(
                save_icon_binding=lambda target_type, target_id, profile_id: None,
            ),
        )
        init_emby_icon_routes(
            require_user=lambda request: True,
            get_emby_user_manager=lambda: manager,
            validate_csrf=lambda request, token: True,
        )

        with patch("emby_users.icon_routes.publish_application_event") as publish:
            response = asyncio.run(
                api_emby_icons_binding_save(
                    payload=IconBindingRequest(
                        target_type="group",
                        target_id="group-1",
                        profile_id="family",
                    ),
                    _csrf=None,
                    user=True,
                ),
            )

        self.assertEqual({"ok": True}, response)
        publish.assert_called_once_with(
            USERS_UPDATED_MESSAGE,
            {"scope": "icons"},
        )

    def test_remote_access_update_notifies_open_user_views(self):
        manager = SimpleNamespace(
            user_ops_manager=SimpleNamespace(
                toggle_remote_access=lambda server_id, user_id, enabled: True,
            ),
        )
        init_emby_user_routes(
            require_user=lambda request: True,
            get_emby_user_manager=lambda: manager,
            validate_csrf=lambda request, token: True,
        )

        with patch("emby_users.routes.publish_application_event") as publish:
            response = asyncio.run(
                api_emby_users_toggle_remote(
                    payload=AccessToggleRequest(server_id="green", user_id="roy", enable=True),
                    _csrf=None,
                    user=True,
                ),
            )

        self.assertEqual({"ok": True}, response)
        publish.assert_called_once_with(
            USERS_UPDATED_MESSAGE,
            {"scope": "dashboard"},
        )

    def test_background_group_sync_notifies_when_it_finishes(self):
        manager = object.__new__(AutoSyncManager)
        manager._operation_tracker = None
        manager._get_users_dashboard_data = lambda: {"groups": []}
        manager._mark_group_sync_result = lambda *args: True
        manager._update_operation = lambda *args, **kwargs: None

        with patch("realtime.manager.publish_application_event") as publish:
            result = manager.run_group_sync("missing")

        self.assertFalse(result["ok"])
        self.assertEqual(
            [
                ((USERS_UPDATED_MESSAGE, {"scope": "sync"}), {}),
                ((USERS_UPDATED_MESSAGE, {"scope": "operations"}), {}),
            ],
            publish.call_args_list,
        )
