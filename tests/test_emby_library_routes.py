import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from emby_libraries.routes import (
    LIBRARIES_UPDATED_MESSAGE,
    emby_associations_post,
    init_emby_library_routes,
    scan_jobs_reset,
)


class EmbyLibraryRoutesTests(unittest.TestCase):
    def setUp(self):
        init_emby_library_routes(
            require_auth=lambda request: True,
            validate_csrf=lambda request, token: token == "valid",
            error_response=lambda message, status_code=400: None,
            success_response=lambda **payload: None,
            ensure_db_backend=lambda: object(),
            load_config=lambda: ({"EMBY": {"SERVERS": []}}, True),
        )

    def test_saving_associations_notifies_open_library_views(self):
        async def body():
            return []

        request = SimpleNamespace(headers={"X-CSRF-Token": "valid"}, json=body)
        with patch(
            "emby_libraries.routes._build_associations_post_snapshot",
            return_value=({"success": True, "associations": []}, 200),
        ), patch("emby_libraries.routes.publish_application_event") as publish:
            response = asyncio.run(emby_associations_post(request))

        self.assertEqual(response.status_code, 200)
        publish.assert_called_once_with(
            LIBRARIES_UPDATED_MESSAGE,
            {"scope": "associations"},
        )

    def test_scan_jobs_reset_lives_in_main_library_router_and_notifies_history(self):
        request = SimpleNamespace(headers={"X-CSRF-Token": "valid"})
        with patch(
            "emby_libraries.routes._clear_library_scan_state",
            new_callable=AsyncMock,
        ) as clear_state, patch("emby_libraries.routes.publish_application_event") as publish:
            response = asyncio.run(scan_jobs_reset(request))

        self.assertEqual(response.status_code, 200)
        clear_state.assert_awaited_once()
        publish.assert_called_once_with(
            LIBRARIES_UPDATED_MESSAGE,
            {"scope": "history"},
        )
