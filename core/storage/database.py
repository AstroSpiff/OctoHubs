"""Storage backends for OctoHubs."""

from __future__ import annotations

import threading
from typing import Any, Dict

from core.storage.storage_errors import StorageError
from core.storage.storage_models import SQLALCHEMY_AVAILABLE
from core.storage.storage_utils import _build_connection_url
from core.storage.storage_app_settings import StorageAppSettingsMixin
from core.storage.storage_image_cache import StorageImageCacheMixin
from core.storage.storage_jellyseerr import StorageJellyseerrMixin
from core.storage.storage_collections import StorageCollectionsMixin
from core.storage.storage_justwatch import StorageJustWatchMixin
from core.storage.storage_core import StorageCoreMixin
from core.storage.storage_latest import StorageLatestMixin
from core.storage.storage_latest_notifications import StorageLatestNotificationMixin
from core.storage.storage_maintenance import StorageMaintenanceMixin
from core.storage.storage_requests import StorageRequestsMixin
from core.storage.storage_manual_search import StorageManualSearchMixin
from core.storage.storage_probe import StorageProbeMixin
from core.storage.storage_users import StorageUsersMixin
from core.storage.storage_workflows import StorageWorkflowMixin


def is_sqlalchemy_available() -> bool:
    return SQLALCHEMY_AVAILABLE


class DatabaseStorage(
    StorageAppSettingsMixin,
    StorageCoreMixin,
    StorageWorkflowMixin,
    StorageManualSearchMixin,
    StorageLatestNotificationMixin,
    StorageLatestMixin,
    StorageJellyseerrMixin,
    StorageImageCacheMixin,
    StorageRequestsMixin,
    StorageProbeMixin,
    StorageUsersMixin,
    StorageCollectionsMixin,
    StorageJustWatchMixin,
    StorageMaintenanceMixin
):
    """SQLAlchemy-backed storage for configuration, request rules and results."""

    def __init__(self, settings: Dict[str, Any], *, app_settings_cipher: Any = None):
        if not SQLALCHEMY_AVAILABLE:  # pragma: no cover - runtime guard
            raise StorageError(
                "Per usare il database installa SQLAlchemy e un driver PostgreSQL (es. psycopg2)."
            )
        self.settings = settings
        self.url = _build_connection_url(settings)
        self._engine: Any = None
        self._Session: Any = None
        self._lock = threading.Lock()
        self._app_settings_lock = threading.RLock()
        self._app_settings_cipher = app_settings_cipher

    def _get_session(self) -> Any:
        if self._Session is None:
            self.ensure_ready()
        return self._Session()


__all__ = ["DatabaseStorage", "StorageError", "is_sqlalchemy_available"]
