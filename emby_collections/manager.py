"""Helper module for managing Emby collection definitions."""

from emby_collections.collection_common import (
    COLLECTION_POSTER_MAX_BYTES,
    COLLECTION_POSTER_MIME_TYPES,
)
from emby_collections.collection_store import (
    delete_collection_backdrop_blob,
    delete_collection_poster_blob,
    get_collection_backdrop_blob,
    get_collection_poster_blob,
    get_collection_sync_details,
    list_collection_definitions,
    remove_collection_definition,
    save_collection_backdrop_blob,
    save_collection_definition,
    save_collection_poster_blob,
    set_collection_enabled,
)
from emby_collections.collection_sync import run_collection_sync, sync_all_collections

__all__ = [
    "COLLECTION_POSTER_MAX_BYTES",
    "COLLECTION_POSTER_MIME_TYPES",
    "delete_collection_backdrop_blob",
    "delete_collection_poster_blob",
    "get_collection_backdrop_blob",
    "get_collection_poster_blob",
    "get_collection_sync_details",
    "list_collection_definitions",
    "remove_collection_definition",
    "run_collection_sync",
    "save_collection_backdrop_blob",
    "save_collection_definition",
    "save_collection_poster_blob",
    "set_collection_enabled",
    "sync_all_collections",
]
