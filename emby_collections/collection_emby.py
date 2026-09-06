"""Emby API helpers for collection management."""

from __future__ import annotations

import base64
import logging
import time
from typing import Any, Dict, List, Tuple

import requests

from core.log_sanitization import (
    format_exception_for_log,
    sanitize_diagnostic_text,
    sanitize_url_for_log,
)
from emby_runtime.api_clients import _call_emby_api, _emby_base_url, EMBY_REQUEST_TIMEOUT
from .collection_common import (
    COLLECTION_BATCH_SIZE,
    _build_collection_tags,
    _extract_emby_items,
    _octohubs_id_tag,
)
from .sources import PROVIDER_LABEL_MAP

logger = logging.getLogger(__name__)


def _entry_provider_candidates(entry: Dict[str, Any]) -> List[Tuple[str, str, str]]:
    provider_key = str(entry.get("provider_key") or "").strip()
    provider_id = str(entry.get("provider_id") or "").strip()
    if not provider_key or not provider_id:
        return []
    provider_label = str(
        entry.get("provider_label") or PROVIDER_LABEL_MAP.get(provider_key, provider_key.title())
    )
    candidates = [(provider_key, provider_id, provider_label)]
    tmdb_id = str(entry.get("tmdb_id") or "").strip()
    if tmdb_id and (provider_key.lower() != "tmdb" or provider_id != tmdb_id):
        candidates.append(("tmdb", tmdb_id, PROVIDER_LABEL_MAP.get("tmdb", "Tmdb")))
    return candidates


def _find_emby_item_ids(server: Dict[str, Any], entry: Dict[str, Any]) -> List[str]:
    candidates = _entry_provider_candidates(entry)
    if not candidates:
        return []
    for _provider_key, provider_id, provider_label in candidates:
        params = {
            "AnyProviderIdEquals": f"{provider_label}.{provider_id}",
            "Recursive": "true",
            "Fields": "ProviderIds"
        }
        media_type = entry.get("media_type")
        if media_type == "movie":
            params["IncludeItemTypes"] = "Movie"
        elif media_type == "tv":
            params["IncludeItemTypes"] = "Series"
        success, payload = _call_emby_api(server, "Items", params=params)
        if not success:
            logger.warning("Errore ricerca Emby %s: %s", provider_label, payload)
            continue
        items = payload.get("Items") if isinstance(payload, dict) else payload if isinstance(payload, list) else []
        result = []
        if isinstance(items, list):
            for item in items:
                if isinstance(item, dict):
                    item_id = item.get("Id")
                    if item_id:
                        result.append(item_id)
        if result:
            logger.info("Trovati %d elementi Emby per %s.%s", len(result), provider_label, provider_id)
            return result
    return []


def _ensure_emby_collection(server: Dict[str, Any], name: str, sort_name: str, initial_item_ids: List[str] | None = None) -> Tuple[str, bool]:
    success, payload = _call_emby_api(server, "Collections", method="GET")
    existing = []
    if isinstance(payload, dict):
        existing = payload.get("Items") or []
    elif isinstance(payload, list):
        existing = payload
    for entry in existing:
        if not isinstance(entry, dict):
            continue
        entry_id = entry.get("Id")
        if entry_id and (entry.get("SortName") == sort_name or entry.get("Name") == name):
            identifier = str(entry_id)
            logger.info("Usata collezione esistente %s (%s)", name, identifier)
            return identifier, False
    payload = {
        "Name": name,
        "SortName": sort_name or name,
        "CollectionType": "User"
    }
    params = {}
    if initial_item_ids:
        valid_ids: List[str] = [
            str(item)
            for item in initial_item_ids
            if item
        ]
        if valid_ids:
            params["Ids"] = ",".join(valid_ids)
    created, response = _call_emby_api(
        server,
        "Collections",
        method="POST",
        json_payload=payload,
        params=params or None
    )
    if not created or not isinstance(response, dict) or not response.get("Id"):
        raise RuntimeError(f"Impossibile creare collezione: {response}")
    collection_id = response["Id"]
    logger.info("Creata collezione %s (id=%s)", name, collection_id)
    return collection_id, True


def _chunk_items(items: List[str], size: int) -> List[List[str]]:
    return [items[i:i + size] for i in range(0, len(items), size)]


def _update_collection_items(server: Dict[str, Any], collection_id: str, item_ids: List[str]) -> None:
    if not item_ids:
        logger.info("Nessun elemento da aggiungere per collezione %s", collection_id)
        return
    valid_ids = [str(item) for item in item_ids if item]
    if not valid_ids:
        logger.info("Nessun ID valido per collezione %s", collection_id)
        return
    added = 0
    batches = _chunk_items(valid_ids, COLLECTION_BATCH_SIZE)
    for batch in batches:
        params = {"Ids": ",".join(batch)}
        success, response = _call_emby_api(
            server,
            f"Collections/{collection_id}/Items",
            method="POST",
            params=params
        )
        if not success:
            logger.warning("Errore aggiornamento collezione %s: %s", collection_id, response)
            raise RuntimeError(response)
        added += len(batch)
        logger.info("Collezione %s aggiornata con batch da %d elementi", collection_id, len(batch))
    if added:
        logger.info("Collezione %s aggiornata con %d elementi totali", collection_id, added)


def _delete_emby_collection(server: Dict[str, Any], collection_id: str) -> bool:
    if not collection_id:
        return False
    success, response = _call_emby_api(
        server,
        f"Items/{collection_id}",
        method="DELETE",
        params={"Recursive": "true"}
    )
    if success:
        logger.info("Collezione Emby %s cancellata via Items", collection_id)
        return True
    fallback_success, fallback_response = _call_emby_api(
        server,
        f"Collections/{collection_id}",
        method="DELETE"
    )
    if fallback_success:
        logger.info("Collezione Emby %s cancellata via Collections", collection_id)
        return True
    logger.warning(
        "Impossibile cancellare collezione %s: %s",
        collection_id,
        fallback_response or response
    )
    return False


def _find_existing_collection_id(server: Dict[str, Any], name: str, sort_name: str) -> str | None:
    def _match_collection(payload: Any) -> str | None:
        for entry in _extract_emby_items(payload):
            entry_id = entry.get("Id")
            if not entry_id:
                continue
            if entry.get("SortName") == sort_name or entry.get("Name") == name:
                return entry_id
        return None

    user_id = _get_api_user_id(server)
    params = {
        "IncludeItemTypes": "BoxSet",
        "Recursive": "true",
        "Fields": "SortName,Name"
    }
    if user_id:
        success, payload = _call_emby_api(server, f"Users/{user_id}/Items", params=params)
        if success:
            match = _match_collection(payload)
            if match:
                return match
    success, payload = _call_emby_api(server, "Items", params=params)
    if success:
        match = _match_collection(payload)
        if match:
            return match
    success, payload = _call_emby_api(server, "Collections", method="GET")
    if not success:
        logger.warning("Impossibile recuperare collezioni: %s", payload)
        return None
    return _match_collection(payload)


def _clear_collection_items(server: Dict[str, Any], collection_id: str) -> int:
    if not collection_id:
        return 0
    success, payload = _call_emby_api(
        server,
        f"Collections/{collection_id}/Items",
        method="GET",
        params={"Fields": "Id"}
    )
    if not success:
        logger.warning("Errore lettura collezione %s: %s", collection_id, payload)
        return 0
    items = [item.get("Id") for item in _extract_emby_items(payload) if item.get("Id")]
    valid_items = [str(item) for item in items if isinstance(item, str) and item]
    if not valid_items:
        return 0
    removed, removal_response = _call_emby_api(
        server,
        f"Collections/{collection_id}/Items",
        method="DELETE",
        params={"Ids": ",".join(valid_items)}
    )
    if not removed:
        logger.warning("Errore svuotamento collezione %s: %s", collection_id, removal_response)
        raise RuntimeError(removal_response)
    if removal_response and not isinstance(removal_response, str):
        logger.debug("Clear collection response: %s", removal_response)
    logger.info("Collezione %s svuotata (%d elementi)", collection_id, len(items))
    return len(items)


def _set_collection_poster(server: Dict[str, Any], collection_id: str, poster_url: str) -> None:
    if not collection_id or not poster_url:
        return
    payload = {
        "Type": "Primary",
        "ImageUrl": poster_url,
        "ProviderName": "OctoHubs Collections"
    }
    success, response = _call_emby_api(
        server,
        f"Items/{collection_id}/RemoteImages/Download",
        method="POST",
        json_payload=payload
    )
    if success:
        logger.info(
            "Poster della collezione %s aggiornato da %s",
            sanitize_diagnostic_text(collection_id),
            sanitize_diagnostic_text(sanitize_url_for_log(poster_url)),
        )
    else:
        logger.warning("Impossibile impostare poster per %s: %s", collection_id, response)


def _set_collection_background(server: Dict[str, Any], collection_id: str, background_url: str) -> None:
    if not collection_id or not background_url:
        return
    payload = {
        "Type": "Backdrop",
        "ImageUrl": background_url,
        "ProviderName": "OctoHubs Collections"
    }
    success, response = _call_emby_api(
        server,
        f"Items/{collection_id}/RemoteImages/Download",
        method="POST",
        json_payload=payload
    )
    if success:
        logger.info(
            "Backdrop della collezione %s aggiornato da %s",
            sanitize_diagnostic_text(collection_id),
            sanitize_diagnostic_text(sanitize_url_for_log(background_url)),
        )
    else:
        logger.warning("Impossibile impostare backdrop per %s: %s", collection_id, response)


def _set_collection_poster_blob(
    server: Dict[str, Any],
    collection_id: str,
    poster_blob: bytes,
    mime_type: str
) -> None:
    if not collection_id or not poster_blob:
        return
    base_url = _emby_base_url(server)
    token = (server.get("api_key") or "").strip()
    if not base_url or not token:
        logger.warning("Credenziali Emby mancanti per upload poster %s", collection_id)
        return
    headers = {
        "X-Emby-Token": token,
        "Content-Type": mime_type or "application/octet-stream"
    }
    target = f"{base_url}/Items/{collection_id}/Images/Primary"
    try:
        encoded = base64.b64encode(poster_blob)
        response = requests.post(
            target,
            headers=headers,
            data=encoded,
            allow_redirects=False,
            timeout=EMBY_REQUEST_TIMEOUT
        )
        if response.is_redirect or response.is_permanent_redirect:
            logger.warning("Redirect rifiutato durante upload poster %s", collection_id)
            return
        if response.status_code in (200, 204):
            logger.info("Poster della collezione %s caricato da blob", collection_id)
        else:
            logger.warning("Impossibile caricare poster %s: HTTP %s", collection_id, response.status_code)
    except requests.RequestException as exc:
        logger.warning("Errore upload poster %s:\n%s", collection_id, format_exception_for_log(exc))


def _set_collection_background_blob(
    server: Dict[str, Any],
    collection_id: str,
    background_blob: bytes,
    mime_type: str
) -> None:
    if not collection_id or not background_blob:
        return
    base_url = _emby_base_url(server)
    token = (server.get("api_key") or "").strip()
    if not base_url or not token:
        logger.warning("Credenziali Emby mancanti per upload backdrop %s", collection_id)
        return
    headers = {
        "X-Emby-Token": token,
        "Content-Type": mime_type or "application/octet-stream"
    }
    target = f"{base_url}/Items/{collection_id}/Images/Backdrop"
    try:
        encoded = base64.b64encode(background_blob)
        response = requests.post(
            target,
            headers=headers,
            data=encoded,
            allow_redirects=False,
            timeout=EMBY_REQUEST_TIMEOUT
        )
        if response.is_redirect or response.is_permanent_redirect:
            logger.warning("Redirect rifiutato durante upload backdrop %s", collection_id)
            return
        if response.status_code in (200, 204):
            logger.info("Backdrop della collezione %s caricato da blob", collection_id)
        else:
            logger.warning("Impossibile caricare backdrop %s: HTTP %s", collection_id, response.status_code)
    except requests.RequestException as exc:
        logger.warning("Errore upload backdrop %s:\n%s", collection_id, format_exception_for_log(exc))


def _build_item_path(server: Dict[str, Any], item_id: str) -> str:
    user_id = (
        str(server.get("user_id") or server.get("userId") or server.get("UserId") or "").strip()
    )
    if user_id:
        return f"Users/{user_id}/Items/{item_id}"
    return f"Items/{item_id}"


def _select_primary_user_id(users_payload: Any) -> str:
    users = users_payload if isinstance(users_payload, list) else (users_payload.get("Items") if isinstance(users_payload, dict) else [])
    if not isinstance(users, list):
        return ""
    admin_id = ""
    fallback_id = ""
    for user in users:
        if not isinstance(user, dict):
            continue
        user_id = str(user.get("Id") or "").strip()
        if not user_id:
            continue
        if not fallback_id:
            fallback_id = user_id
        policy = user.get("Policy")
        if not isinstance(policy, dict):
            policy = {}
        if policy.get("IsAdministrator"):
            admin_id = user_id
            break
    return admin_id or fallback_id


def _get_api_user_id(server: Dict[str, Any]) -> str:
    for path in ("Users/Me", "Users/Current"):
        success, payload = _call_emby_api(server, path)
        if success and isinstance(payload, dict):
            candidate = str(payload.get("Id") or payload.get("UserId") or "").strip()
            if candidate:
                return candidate
    success, users_payload = _call_emby_api(server, "Users")
    if success:
        return _select_primary_user_id(users_payload)
    return ""


def _fetch_collection_item(server: Dict[str, Any], collection_id: str) -> tuple[Dict[str, Any] | None, bool]:
    user_id = _get_api_user_id(server)
    if user_id:
        success, payload = _call_emby_api(server, f"Users/{user_id}/Items/{collection_id}")
        if success and isinstance(payload, dict):
            source_value = payload.get("Source")
            return payload, bool(isinstance(source_value, dict) and source_value)
    direct_success, direct_payload = _call_emby_api(server, f"Items/{collection_id}")
    if direct_success and isinstance(direct_payload, dict):
        source_value = direct_payload.get("Source")
        return direct_payload, bool(isinstance(source_value, dict) and source_value)
    return None, False


def _list_emby_collections(server: Dict[str, Any]) -> Tuple[List[Dict[str, Any]], bool]:
    params = {
        "IncludeItemTypes": "BoxSet",
        "Recursive": "true",
        "Fields": "SortName,Name,Tags"
    }
    user_id = _get_api_user_id(server)
    if user_id:
        success, payload = _call_emby_api(server, f"Users/{user_id}/Items", params=params)
        if success:
            return _extract_emby_items(payload), True
    success, payload = _call_emby_api(server, "Items", params=params)
    if success:
        return _extract_emby_items(payload), True
    success, payload = _call_emby_api(server, "Collections", method="GET")
    if success:
        return _extract_emby_items(payload), True
    return [], False


def _find_collection_ids_for_definition(
    server: Dict[str, Any],
    definition: Dict[str, Any]
) -> Tuple[List[str], bool]:
    name = str(definition.get("name") or "").strip()
    sort_name = str(definition.get("sort_name") or "").strip()
    definition_id = str(definition.get("id") or "").strip()
    id_tag = _octohubs_id_tag(definition_id) if definition_id else ""
    matches: List[str] = []
    entries, ok = _list_emby_collections(server)
    if not ok:
        return [], False
    for entry in entries:
        entry_id = entry.get("Id")
        if not entry_id:
            continue
        raw_tags = entry.get("Tags")
        tags = [str(tag) for tag in raw_tags if tag] if isinstance(raw_tags, list) else []
        if id_tag and id_tag in tags:
            matches.append(entry_id)
            continue
        if name and entry.get("Name") == name:
            matches.append(entry_id)
            continue
        if sort_name and entry.get("SortName") == sort_name:
            matches.append(entry_id)
    return list(dict.fromkeys(matches)), True


def _apply_collection_properties(server: Dict[str, Any], collection_id: str, definition: Dict[str, Any]) -> None:
    if not collection_id:
        return
    item, has_source = _fetch_collection_item(server, collection_id)
    if item is None:
        logger.warning(
            "Impossibile recuperare collezione %s prima di aggiornare",
            collection_id
        )
        return
    # Tenta di attendere il campo Source, ma procedi comunque se non disponibile
    if not has_source:
        for _ in range(3):
            time.sleep(0.5)
            item, has_source = _fetch_collection_item(server, collection_id)
            if item and has_source:
                break
        if item is None:
            logger.warning(
                "Impossibile recuperare collezione %s dopo retry",
                collection_id
            )
            return
        if not has_source:
            logger.info(
                "Collezione %s senza Source valido, procedo comunque con l'aggiornamento delle proprietà base",
                collection_id
            )
    payload: Dict[str, Any] = {}
    description = (definition.get("collection_description") or "").strip()
    if not description and definition.get("use_source_description"):
        description = definition.get("source_description") or ""
    if description:
        payload["Overview"] = description
    name = (definition.get("name") or item.get("Name") or "").strip()
    if name:
        payload["Name"] = name
    sort_override = (definition.get("collection_sort_name") or definition.get("sort_name") or name).strip()
    if sort_override:
        payload["SortName"] = sort_override
        payload["ForcedSortName"] = sort_override
    locked_fields_raw = item.get("LockedFields")
    if isinstance(locked_fields_raw, list):
        locked_fields = [field for field in locked_fields_raw if isinstance(field, str)]
    else:
        locked_fields = []
    if "SortName" not in locked_fields:
        locked_fields.append("SortName")
    if "Name" not in locked_fields:
        locked_fields.append("Name")
    if locked_fields:
        payload["LockedFields"] = locked_fields
    tags = _build_collection_tags(definition, item.get("Tags"))
    if tags:
        payload["Tags"] = tags
    source_value = item.get("Source") if isinstance(item.get("Source"), dict) else None
    if isinstance(source_value, dict) and source_value:
        payload["Source"] = source_value
    if not payload:
        return
    logger.info(
        "Aggiornamento collezione %s sul server %s con payload %s",
        collection_id,
        server.get("id"),
        payload
    )
    item.update(payload)
    success, response = _call_emby_api(
        server,
        f"Items/{collection_id}",
        method="POST",
        json_payload=item
    )
    if not success:
        logger.warning("Impossibile aggiornare proprietà collezione %s: %s", collection_id, response)
    else:
        logger.info("Proprietà collezione %s aggiornate con successo", collection_id)


def _fetch_items_metadata(server: Dict[str, Any], item_ids: List[str], fields: List[str]) -> Dict[str, Dict[str, Any]]:
    if not item_ids:
        return {}
    params = {
        "Ids": ",".join(item_ids),
        "Fields": ",".join(set(fields))
    }
    success, payload = _call_emby_api(server, "Items", params=params)
    if not success:
        logger.warning("Impossibile leggere i metadati degli item (%s)", payload)
        return {}
    items = _extract_emby_items(payload)
    return {item["Id"]: item for item in items if item.get("Id")}


def _refresh_items_metadata(server: Dict[str, Any], item_ids: List[str]) -> None:
    if not item_ids:
        return
    for item_id in item_ids:
        success, response = _call_emby_api(
            server,
            f"Items/{item_id}/Refresh",
            method="POST",
            params={"ReplaceAllMetadata": "true"}
        )
        if not success:
            logger.warning("Errore refresh metadata per %s: %s", item_id, response)
