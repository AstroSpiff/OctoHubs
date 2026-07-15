"""Snapshot builders for Emby ordering and tab layout."""

from __future__ import annotations

import copy

from core.config_manager import _ensure_db_backend, load_config
from core.storage import StorageError
from core.utils import json_error, json_success
from emby_runtime.settings_manager import _load_emby_settings_from_db, _save_emby_settings_to_db


def _build_server_order_snapshot(payload):
    if not isinstance(payload, list):
        return json_error("Formato non valido")
    try:
        _ensure_db_backend()
    except StorageError as exc:
        return json_error(f"Errore DB: {exc}", 500)
    emby_section = _load_emby_settings_from_db()
    servers = copy.deepcopy(emby_section.get("SERVERS") or [])
    server_map = {server.get("id"): server for server in servers if server.get("id")}
    ordered = []
    for entry in payload:
        if not isinstance(entry, str):
            continue
        server = server_map.get(entry)
        if server:
            ordered.append(server)
    remaining = [server for server in servers if server.get("id") not in payload]
    ordered.extend(remaining)
    _save_emby_settings_to_db({"SERVERS": ordered})
    load_config()
    return json_success()


def _build_group_order_get_snapshot():
    try:
        backend = _ensure_db_backend()
        order_map = backend.load_library_group_order()
    except StorageError as exc:
        return json_error(f"Errore DB: {exc}", 500)
    payload = [
        {
            "collection_type": collection_type,
            "group_name": group_name,
            "position": position
        }
        for (collection_type, group_name), position in order_map.items()
    ]
    return {"success": True, "order": payload}, 200


def _build_group_order_post_snapshot(payload):
    if not isinstance(payload, list):
        return json_error("Formato non valido")
    positions = {}
    for entry in payload:
        if not isinstance(entry, dict):
            continue
        collection_type = entry.get("collection_type")
        group_name = entry.get("group_name")
        position = entry.get("position")
        if collection_type is None or group_name is None or position is None:
            continue
        positions[(str(collection_type), str(group_name))] = int(position)
    try:
        backend = _ensure_db_backend()
        backend.save_library_group_order(positions)
    except StorageError as exc:
        return json_error(f"Errore DB: {exc}", 500)
    return {"success": True, "order": payload}, 200


def _build_tab_order_get_snapshot(page):
    if not page:
        return json_error("Pagina mancante")
    try:
        backend = _ensure_db_backend()
        order_map = backend.load_tab_order(page)
    except StorageError as exc:
        return json_error(f"Errore DB: {exc}", 500)
    payload = [
        {"tab_key": tab_key, "position": position}
        for tab_key, position in order_map.items()
    ]
    return {"success": True, "order": payload}, 200


def _build_tab_order_post_snapshot(payload):
    payload = payload or {}
    if not isinstance(payload, dict):
        return json_error("Formato non valido")
    page = payload.get("page")
    order = payload.get("order")
    if not page or not isinstance(order, list):
        return json_error("Dati mancanti")
    positions = {}
    for entry in order:
        if not isinstance(entry, dict):
            continue
        tab_key = entry.get("tab_key")
        position = entry.get("position")
        if tab_key is None or position is None:
            continue
        positions[str(tab_key)] = int(position)
    try:
        backend = _ensure_db_backend()
        backend.save_tab_order(str(page), positions)
    except StorageError as exc:
        return json_error(f"Errore DB: {exc}", 500)
    return {"success": True, "order": order}, 200
