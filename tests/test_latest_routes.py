import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from core.storage import StorageError

from emby_latest.routes import (
    LATEST_UPDATED_MESSAGE,
    emby_latest_preset_save,
    emby_latest_refresh,
    init_emby_latest_routes,
)


class LatestRoutesTests(unittest.TestCase):
    def setUp(self):
        init_emby_latest_routes(
            require_auth=lambda request: True,
            validate_csrf=lambda request, token: True,
        )

    def test_saving_a_preset_notifies_open_latest_configuration_views(self):
        async def body():
            return {"name": "Base", "template": "{{ title }}"}

        request = SimpleNamespace(headers={}, json=body)
        with patch(
            "emby_latest.configuration_api.save_latest_preset",
            return_value=({"success": True}, 200),
        ), patch("emby_latest.routes.publish_application_event") as publish:
            response = asyncio.run(emby_latest_preset_save(request))

        self.assertEqual(response.status_code, 200)
        publish.assert_called_once_with(
            LATEST_UPDATED_MESSAGE,
            {"scope": "configuration"},
        )

    def test_latest_refresh_rejects_an_invalid_csrf_token(self):
        init_emby_latest_routes(
            require_auth=lambda request: True,
            validate_csrf=lambda request, token: False,
        )
        request = SimpleNamespace(query_params={})

        with patch("emby_latest.routes.api_handlers.build_latest_refresh_payload") as refresh:
            response = asyncio.run(emby_latest_refresh(request))

        self.assertEqual(response.status_code, 403)
        refresh.assert_not_called()

    def test_failed_preset_write_returns_500_without_publishing(self):
        async def body():
            return {"name": "Base", "template": "{{ title }}"}

        request = SimpleNamespace(headers={}, json=body)
        with patch(
            "emby_latest.configuration_api.save_latest_preset",
            side_effect=StorageError("write failed"),
        ), patch("emby_latest.routes.publish_application_event") as publish:
            response = asyncio.run(emby_latest_preset_save(request))

        self.assertEqual(response.status_code, 500)
        self.assertFalse(response.body.startswith(b'{"success":true'))
        publish.assert_not_called()
