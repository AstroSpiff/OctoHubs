import asyncio
import json
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import HTTPException
import pytest

from realtime.routes import emby_status_snapshot_api, init_realtime_routes


def test_status_snapshot_requires_authentication():
    def reject_auth(_request):
        raise HTTPException(status_code=401, detail="Autenticazione richiesta")

    init_realtime_routes(reject_auth)

    with patch("realtime.routes._build_emby_status_stream_payload") as snapshot:
        with pytest.raises(HTTPException, match="Autenticazione richiesta"):
            asyncio.run(emby_status_snapshot_api(SimpleNamespace()))

    snapshot.assert_not_called()


def test_status_snapshot_returns_the_same_payload_as_the_live_feed():
    init_realtime_routes(lambda _request: True)
    payload = {"success": True, "servers": {"green": {"status": {"ok": True}}}}

    with patch("realtime.routes._build_emby_status_stream_payload", return_value=payload):
        response = asyncio.run(emby_status_snapshot_api(SimpleNamespace()))

    assert response.status_code == 200
    assert response.media_type == "application/json"
    assert json.loads(response.body) == payload
