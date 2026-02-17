"""API client helpers for Emby user management."""

import logging

from api_clients import _call_emby_api

__all__ = [
    "_fetch_emby_users_list",
    "_fetch_emby_user_details",
    "_update_emby_user_policy",
    "_update_emby_user_configuration",
    "_rename_emby_user",
    "_update_emby_user_password",
    "_fetch_emby_user_last_playback",
    "_fetch_emby_user_items_for_sync",
    "_fetch_emby_items_by_provider_ids",
    "_mark_emby_item_played",
    "_mark_emby_item_unplayed",
    "_set_emby_item_resume",
    "_create_emby_user",
]


def _fetch_emby_users_list(server):
    """
    Recupera la lista di tutti gli utenti dal server Emby.
    """
    success, payload = _call_emby_api(server, "Users")
    if not success:
        return [], payload
    # Emby restituisce una lista diretta di oggetti User
    if isinstance(payload, list):
        return payload, None
    return [], "Formato risposta inatteso"


def _fetch_emby_user_details(server, user_id):
    """
    Recupera i dettagli completi di un utente, incluse Policy e Configuration.
    """
    if not user_id:
        return None, "User ID mancante"
    success, payload = _call_emby_api(server, f"Users/{user_id}")
    if success:
        return payload, None
    return None, payload


def _update_emby_user_policy(server, user_id, policy):
    """
    Aggiorna la policy di un utente (es. permessi, accessi).
    """
    if not user_id or not isinstance(policy, dict):
        return False, "Dati non validi"

    # Emby richiede una POST su /Users/{Id}/Policy
    success, payload = _call_emby_api(
        server,
        f"Users/{user_id}/Policy",
        method="POST",
        json_payload=policy
    )
    return success, payload


def _update_emby_user_configuration(server, user_id, configuration):
    """
    Aggiorna la configurazione utente (es. preferenze UI, lingua).
    """
    if not user_id or not isinstance(configuration, dict):
        return False, "Dati non validi"

    # Emby richiede una POST su /Users/{Id}/Configuration
    success, payload = _call_emby_api(
        server,
        f"Users/{user_id}/Configuration",
        method="POST",
        json_payload=configuration
    )
    return success, payload


def _rename_emby_user(server, user_id, new_name):
    """
    Rinomina un utente sul server Emby.
    """
    if not user_id or not new_name:
        return False, "Dati mancanti"

    # 1. Fetch current user details
    user_dto, err = _fetch_emby_user_details(server, user_id)
    if err or not user_dto:
        return False, f"Impossibile recuperare utente: {err}"

    # 2. Update Name
    user_dto["Name"] = new_name

    # CRITICAL: Remove Password fields to prevent accidental reset!
    # Emby API /Users/{Id} POST update might clear password if these are present but empty/null.
    # We strip them to be safe.
    keys_to_remove = ["Password", "OriginalPassword", "EasyPassword", "Salt", "PasswordSalt", "ConnectPassword"]
    for k in keys_to_remove:
        user_dto.pop(k, None)

    # 3. Post update
    # Endpoint: /Users/{Id}
    success, payload = _call_emby_api(
        server,
        f"Users/{user_id}",
        method="POST",
        json_payload=user_dto
    )
    return success, payload


def _update_emby_user_password(server, user_id, new_password):
    """
    Aggiorna la password dell'utente.
    Richiede privilegi amministrativi (API Key) per ignorare la password corrente.
    """
    if not user_id:
        return False, "User ID mancante"

    # Endpoint: /Users/{Id}/Password
    payload = {
        "Id": user_id,
        "NewPw": new_password
        # "CurrentPassword": "" # Admin can typically omit this
    }

    success, resp = _call_emby_api(
        server,
        f"Users/{user_id}/Password",
        method="POST",
        json_payload=payload
    )
    return success, resp


def _fetch_emby_user_last_playback(server, user_id):
    """
    Recupera l'ultimo elemento riprodotto dall'utente.
    """
    if not user_id:
        return None

    params = {
        "Recursive": "true",
        "Limit": 1,
        "SortBy": "DatePlayed",
        "SortOrder": "Descending",
        "Filters": "IsPlayed",
        "IncludeItemTypes": "Movie,Episode",
        "Fields": "DatePlayed,Name,SeriesName"
    }

    success, payload = _call_emby_api(server, f"Users/{user_id}/Items", params=params)
    if not success or not isinstance(payload, dict):
        return None

    items = payload.get("Items", [])
    if items:
        return items[0]
    return None


def _fetch_emby_user_items_for_sync(server, user_id, include_resume: bool = True):
    """
    Scarica tutti gli elementi (Film/Episodi) visti o in corso per l'utente,
    con ProviderIds per il matching.
    """
    if not user_id:
        return [], "User ID mancante"

    # Filtriamo per Items ricorsivi, solo Video (Movie, Episode),
    # richiediamo ProviderIds e UserData.
    # Utile filtrare anche "IsPlayed=true" o "IsResumable=true" per ridurre il carico,
    # ma se vogliamo sincronizzare tutto lo storico (anche play count > 0), meglio prendere tutto
    # ciò che ha UserData != null. Emby non ha un filtro "HasUserData", ma possiamo usare
    # "Recursive=true" e poi filtrare lato client, oppure filtrare per "IsPlayed=true,IsResumable=true"
    # in due chiamate o OR se supportato.
    # Per semplicità di sync (copiare esattamente lo stato), prendiamo tutto ciò che è Played o ha resume.

    params = {
        "Recursive": "true",
        "Fields": "ProviderIds,UserData,SeriesName,ParentIndexNumber,IndexNumber,ProductionYear,Name,OriginalTitle",
        "IncludeItemTypes": "Movie,Episode",
        # Emby uses Filters=IsPlayed (non IsPlayed=true)
        "Filters": "IsPlayed"
    }

    # 1. Recupera elementi visti (paginati)
    items, err = _fetch_emby_items_paged(server, user_id, params, label="played")
    if err:
        return [], err

    if include_resume:
        # 2. Recupera elementi parzialmente visti (Resumable) se non già inclusi
        # Nota: IsPlayed=true include spesso anche quelli parziali se PlayCount > 0,
        # ma controlliamo esplicitamente i Resumable.
        params_resume = {
            "Recursive": "true",
            "Fields": "ProviderIds,UserData,SeriesName,ParentIndexNumber,IndexNumber,ProductionYear,Name,OriginalTitle",
            "IncludeItemTypes": "Movie,Episode",
            # Per Emby la query usa Filters=IsResumable (non IsResumable=true)
            "Filters": "IsResumable"
        }
        items_res, err_res = _fetch_emby_items_paged(server, user_id, params_resume, label="resumable")
        if not err_res:
            # Merge by Id to avoid duplicates
            seen_ids = set(i["Id"] for i in items)
            for it in items_res:
                if it["Id"] not in seen_ids:
                    items.append(it)

    return items, None


def _fetch_emby_items_paged(server, user_id, params, page_size=200, label=None):
    """
    Helper: fetch Emby items with pagination.
    """
    if not user_id:
        return [], "User ID mancante"

    items = []
    start_index = 0

    while True:
        page_params = dict(params)
        page_params["StartIndex"] = start_index
        page_params["Limit"] = page_size

        success, payload = _call_emby_api(server, f"Users/{user_id}/Items", params=page_params)
        if not success:
            return [], payload

        if not isinstance(payload, dict):
            return [], "Risposta Emby inattesa"

        page_items = payload.get("Items", []) or []
        items.extend(page_items)

        total = payload.get("TotalRecordCount")
        if total is None:
            if len(page_items) < page_size:
                break
        else:
            if start_index + len(page_items) >= total:
                break

        if len(page_items) == 0:
            break

        start_index += len(page_items)

    if label:
        try:
            name = server.get("name") or server.get("alias") or server.get("id") or "server"
            type_counts = {}
            not_played = 0
            for it in items:
                item_type = it.get("Type") or it.get("ItemType") or "Unknown"
                type_counts[item_type] = type_counts.get(item_type, 0) + 1
                if label == "played" and not it.get("UserData", {}).get("Played"):
                    not_played += 1
            type_summary = ", ".join(f"{k}={v}" for k, v in sorted(type_counts.items()))
            logger.info(
                "[Emby Sync] %s: fetched %s items for user %s on %s (types: %s)",
                label,
                len(items),
                user_id,
                name,
                type_summary or "n/a"
            )
            if label == "played" and not_played:
                logger.info(
                    "[Emby Sync] %s: %s items without UserData.Played=true (filter mismatch?)",
                    label,
                    not_played
                )
        except Exception:
            # Avoid breaking sync on logging errors
            pass

    return items, None


def _format_provider_token(provider_key: str) -> str | None:
    if not provider_key:
        return None
    if ":" not in provider_key:
        return provider_key if "." in provider_key else None
    provider, pid = provider_key.split(":", 1)
    provider = provider.strip().lower()
    pid = pid.strip()
    if not provider or not pid:
        return None
    return f"{provider}.{pid}"


def _chunk_list(items, size):
    for i in range(0, len(items), size):
        yield items[i:i + size]


def _fetch_emby_items_by_provider_ids(server, user_id, provider_keys, include_played=False, page_size=200):
    """
    Fetch items on target server by provider IDs using AnyProviderIdEquals.
    provider_keys: list of strings like "tmdb:123", "imdb:tt123", "tvdb:456".
    """
    if not user_id:
        return [], "User ID mancante"

    if not provider_keys:
        return [], None

    tokens = []
    for key in provider_keys:
        token = _format_provider_token(key)
        if token:
            tokens.append(token)

    if not tokens:
        return [], None

    items = []
    seen_ids = set()

    for chunk in _chunk_list(tokens, 100):
        params = {
            "Recursive": "true",
            "Fields": "ProviderIds,UserData,SeriesName,ParentIndexNumber,IndexNumber,ProductionYear,Name,OriginalTitle",
            "IncludeItemTypes": "Movie,Episode",
            "AnyProviderIdEquals": ",".join(chunk),
        }
        if not include_played:
            params["IsPlayed"] = "false"

        chunk_items, err = _fetch_emby_items_paged(server, user_id, params, page_size=page_size)
        if err:
            return [], err

        for it in chunk_items:
            it_id = it.get("Id")
            if it_id and it_id not in seen_ids:
                items.append(it)
                seen_ids.add(it_id)

    return items, None


def _create_emby_user(server, name, copy_from_user_id=None):
    """
    Creates a new user on the Emby server.
    """
    params = {"Name": name}
    if copy_from_user_id:
        params["CopyFromUserId"] = copy_from_user_id

    success, payload = _call_emby_api(
        server,
        "Users/New",
        method="POST",
        json_payload=params
    )
    return success, payload


def _mark_emby_item_played(server, user_id, item_id, date_played=None):
    """
    Segna un elemento come visto (Played).
    """
    if not user_id or not item_id:
        return False, "ID mancanti"

    params = {}
    if date_played:
        params["DatePlayed"] = date_played

    success, payload = _call_emby_api(
        server,
        f"Users/{user_id}/PlayedItems/{item_id}",
        method="POST",
        json_payload=params
    )
    return success, payload


def _mark_emby_item_unplayed(server, user_id, item_id):
    """
    Rimuove lo stato 'visto' da un elemento.
    """
    if not user_id or not item_id:
        return False, "ID mancanti"

    success, payload = _call_emby_api(
        server,
        f"Users/{user_id}/PlayedItems/{item_id}",
        method="DELETE"
    )
    return success, payload


def _set_emby_item_resume(server, user_id, item_id, position_ticks):
    """
    Imposta la posizione di ripresa (resume) per un item.
    """
    if not user_id or not item_id:
        return False, "ID mancanti"
    if position_ticks is None:
        return False, "Resume position mancante"

    params = {"PlaybackPositionTicks": int(position_ticks)}
    success, payload = _call_emby_api(
        server,
        f"Users/{user_id}/Items/{item_id}/UserData",
        method="POST",
        json_payload=params
    )
    return success, payload
logger = logging.getLogger(__name__)
