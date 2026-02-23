from typing import Optional

from emby_runtime.api_clients import _call_emby_api


class EmbyApiClient:
    """Simple wrapper for Emby API calls, used by EmbyLibraryPoller."""

    def __init__(self, server_config: dict):
        self.server_config = server_config

    def get(self, endpoint: str, params: Optional[dict] = None):
        """Execute GET request to Emby API."""
        success, response = _call_emby_api(
            self.server_config,
            endpoint,
            method="GET",
            params=params or {}
        )
        if not success:
            raise Exception(f"Emby API call failed: {response}")
        return response
