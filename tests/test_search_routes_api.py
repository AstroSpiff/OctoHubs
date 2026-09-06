"""Search API route resilience."""

from __future__ import annotations

import unittest

from core.storage import StorageError
from search.routes import get_manual_search_history, init_search_routes


class SearchRouteTests(unittest.IsolatedAsyncioTestCase):
    async def test_manual_history_degrades_to_empty_when_storage_unavailable(self):
        init_search_routes(
            require_auth=lambda _request: {"id": "admin"},
            ensure_db_backend=lambda: (_ for _ in ()).throw(StorageError("tabella mancante")),
            validate_csrf=lambda _request, _token: True,
        )

        response = await get_manual_search_history(object())

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.body.decode(),
            '{"success":true,"searches":[],"warning":"Storico ricerche temporaneamente non disponibile"}',
        )


if __name__ == "__main__":
    unittest.main()
