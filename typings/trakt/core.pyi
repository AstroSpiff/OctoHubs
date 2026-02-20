from typing import Any, Optional

BASE_URL: str
CLIENT_ID: str
CLIENT_SECRET: str
OAUTH_TOKEN: str
OAUTH_REFRESH: str
OAUTH_EXPIRES_AT: int
CONFIG_PATH: Optional[str]

def __getattr__(name: str) -> Any: ...
