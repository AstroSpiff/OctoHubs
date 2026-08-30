"""API client helpers for Emby user items and playback status."""

import logging
from datetime import datetime, timezone

from emby_runtime.api_clients import _call_emby_api
from emby_users.item_matching import get_safe_fallback_signature, matches_safe_fallback_signature

logger = logging.getLogger(__name__)

USER_ITEM_FIELDS = "ProviderIds,SeriesProviderIds,SeriesId,UserData,SeriesName,ParentIndexNumber,IndexNumber,ProductionYear,Name,OriginalTitle,RunTimeTicks,Type"


def _format_emby_date_played(value):
    if not value:
        return None
    text = str(value).strip()
    if not text:
        return None
    if text.isdigit() and len(text) == 14:
        return text
    normalized = text
    if normalized.endswith("Z"):
        normalized = f"{normalized[:-1]}+00:00"
    if "." in normalized:
        prefix, suffix = normalized.split(".", 1)
        timezone_pos = None
        for marker in ("+", "-"):
            pos = suffix.find(marker)
            if pos > 0:
                timezone_pos = pos
                break
        if timezone_pos is None:
            fraction = suffix
            tz_part = ""
        else:
            fraction = suffix[:timezone_pos]
            tz_part = suffix[timezone_pos:]
        normalized = f"{prefix}.{fraction[:6].ljust(6, '0')}{tz_part}"
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        logger.warning("[Emby Sync] DatePlayed non valida, invio senza data: %s", value)
        return None
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(timezone.utc).replace(tzinfo=None)
    return parsed.strftime("%Y%m%d%H%M%S")


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
        # LastPlayedDate lives inside UserData in Emby's item response.
        "Fields": "UserData,SeriesName",
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
        "Fields": USER_ITEM_FIELDS,
        "IncludeItemTypes": "Movie,Episode",
        # Emby uses Filters=IsPlayed (non IsPlayed=true)
        "Filters": "IsPlayed"
    }

    # 1. Recupera elementi visti (paginati)
    items, err = _fetch_emby_items_paged(server, user_id, params, label="played")
    if err:
        return [], err
    _attach_missing_playstate_last_played_dates(server, user_id, items)

    if include_resume:
        # 2. Recupera elementi parzialmente visti (Resumable) se non già inclusi
        # Nota: IsPlayed=true include spesso anche quelli parziali se PlayCount > 0,
        # ma controlliamo esplicitamente i Resumable.
        params_resume = {
            "Recursive": "true",
            "Fields": USER_ITEM_FIELDS,
            "IncludeItemTypes": "Movie,Episode",
            # Per Emby la query usa Filters=IsResumable (non IsResumable=true)
            "Filters": "IsResumable"
        }
        items_res, err_res = _fetch_emby_items_paged(server, user_id, params_resume, label="resumable")
        if not err_res:
            visible_resume_ids, visible_err = _fetch_emby_visible_resume_item_ids(server, user_id)
            if not visible_err:
                _annotate_hide_from_resume(items_res, visible_resume_ids)
            else:
                logger.warning("[Emby Sync] resume visibility fetch failed for user %s: %s", user_id, visible_err)
            _attach_missing_playstate_last_played_dates(server, user_id, items_res)

            # Merge by Id to avoid duplicates, preserving resume-specific UserData.
            items_by_id = {str(i.get("Id")): i for i in items if i.get("Id")}
            for it in items_res:
                item_id = str(it.get("Id") or "")
                if not item_id:
                    continue
                if item_id in items_by_id:
                    _merge_user_item_data(items_by_id[item_id], it)
                else:
                    items.append(it)

    return items, None


def _fetch_emby_visible_resume_item_ids(server, user_id):
    """Return item ids currently visible in Emby's Continue Watching list."""
    params = {
        "Recursive": "true",
        "Fields": USER_ITEM_FIELDS,
        "IncludeItemTypes": "Movie,Episode",
    }
    items, err = _fetch_emby_items_paged(
        server,
        user_id,
        params,
        label="resume-visible",
        path=f"Users/{user_id}/Items/Resume",
    )
    if err:
        return set(), err
    return {str(item.get("Id")) for item in items if item.get("Id")}, None


def _annotate_hide_from_resume(items, visible_resume_ids):
    for item in items:
        item_id = item.get("Id")
        if not item_id:
            continue
        user_data = item.setdefault("UserData", {})
        if not isinstance(user_data, dict):
            user_data = {}
            item["UserData"] = user_data
        if int(user_data.get("PlaybackPositionTicks") or 0) <= 0:
            continue
        user_data["HideFromResume"] = str(item_id) not in visible_resume_ids


def _merge_user_item_data(target, source):
    source_user_data = source.get("UserData") or {}
    if not source_user_data:
        return
    target_user_data = target.setdefault("UserData", {})
    if not isinstance(target_user_data, dict):
        target_user_data = {}
        target["UserData"] = target_user_data
    target_user_data.update(source_user_data)


def _attach_missing_playstate_last_played_dates(server, user_id, items):
    for item in items:
        item_id = item.get("Id")
        if not item_id:
            continue
        user_data = item.get("UserData") or {}
        has_playstate = bool(user_data.get("Played")) or int(user_data.get("PlaybackPositionTicks") or 0) > 0
        if not has_playstate:
            continue
        if user_data.get("LastPlayedDate"):
            continue
        success, payload = _call_emby_api(
            server,
            f"Users/{user_id}/Items/{item_id}",
            params={"Fields": USER_ITEM_FIELDS},
        )
        if not success or not isinstance(payload, dict):
            continue
        detail_user_data = payload.get("UserData") or {}
        if detail_user_data.get("LastPlayedDate"):
            _merge_user_item_data(item, payload)


def _fetch_emby_user_favorite_items(server, user_id):
    """
    Scarica gli elementi preferiti dell'utente.
    """
    if not user_id:
        return [], "User ID mancante"

    params = {
        "Recursive": "true",
        "Fields": USER_ITEM_FIELDS,
        "IncludeItemTypes": "Movie,Episode,Series",
        "Filters": "IsFavorite"
    }
    return _fetch_emby_items_paged(server, user_id, params, label="favorites")


def _fetch_emby_user_media_items(server, user_id):
    """
    Scarica gli item media necessari al matching cross-server.
    """
    if not user_id:
        return [], "User ID mancante"

    params = {
        "Recursive": "true",
        "Fields": USER_ITEM_FIELDS,
        "IncludeItemTypes": "Movie,Episode",
    }
    return _fetch_emby_items_paged(server, user_id, params, label="media")


def _fetch_emby_items_paged(server, user_id, params, page_size=200, label=None, path=None):
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

        api_path = path or f"Users/{user_id}/Items"
        success, payload = _call_emby_api(server, api_path, params=page_params)
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

    _attach_series_provider_ids(server, user_id, items, label=label)

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


def _attach_series_provider_ids(server, user_id, items, label=None):
    """Fill Episode.SeriesProviderIds from its SeriesId when Emby does not include it."""
    series_cache = {}
    provider_key_counts = {}
    episode_count = 0
    missing_provider_count = 0
    missing_series_id_count = 0
    attached_count = 0
    for item in items:
        if not isinstance(item, dict):
            continue
        item_type = item.get("Type") or item.get("ItemType")
        if item_type != "Episode":
            continue
        episode_count += 1
        if item.get("SeriesProviderIds"):
            continue
        missing_provider_count += 1
        series_id = item.get("SeriesId")
        if not series_id:
            missing_series_id_count += 1
            continue
        if series_id not in series_cache:
            success, payload = _call_emby_api(
                server,
                f"Users/{user_id}/Items/{series_id}",
                params={"Fields": "ProviderIds"},
            )
            if not success:
                success, payload = _call_emby_api(server, f"Items/{series_id}", params={"Fields": "ProviderIds"})
            if success and isinstance(payload, dict):
                series_cache[series_id] = payload.get("ProviderIds") or {}
            else:
                series_cache[series_id] = {}
        if series_cache[series_id]:
            item["SeriesProviderIds"] = series_cache[series_id]
            attached_count += 1
            for provider_key in series_cache[series_id].keys():
                key = str(provider_key).lower()
                provider_key_counts[key] = provider_key_counts.get(key, 0) + 1
    if label and episode_count:
        logger.warning(
            "[Emby Sync] %s series ids: episodes=%s missing_series_provider_ids=%s missing_series_id=%s attached=%s unique_series_checked=%s provider_keys=%s",
            label,
            episode_count,
            missing_provider_count,
            missing_series_id_count,
            attached_count,
            len(series_cache),
            provider_key_counts,
        )


def _format_provider_token(provider_key: str) -> str | None:
    if not provider_key:
        return None
    if provider_key.startswith(("series-tmdb:", "series-imdb:", "series-tvdb:")):
        return None
    if ":" not in provider_key:
        return provider_key if "." in provider_key else None
    provider, pid = provider_key.split(":", 1)
    provider = provider.strip().lower()
    pid = pid.strip()
    if not provider or not pid:
        return None
    return f"{provider}.{pid}"


def _parse_series_provider_key(provider_key: str):
    provider_prefixes = {
        "series-tmdb:": "tmdb",
        "series-imdb:": "imdb",
        "series-tvdb:": "tvdb",
    }
    provider = None
    raw = None
    for prefix, candidate in provider_prefixes.items():
        if provider_key.startswith(prefix):
            provider = candidate
            raw = provider_key[len(prefix):]
            break
    if provider is None or raw is None:
        return None

    try:
        series_id, rest = raw.split(":s", 1)
        season, episode = rest.split(":e", 1)
    except ValueError:
        return None

    if not series_id or season == "" or episode == "":
        return None
    return {
        "provider": provider,
        "provider_id": series_id,
        "season": str(season),
        "episode": str(episode),
    }


def _chunk_list(items, size):
    for i in range(0, len(items), size):
        yield items[i:i + size]


def _fetch_emby_items_by_series_provider_keys(server, user_id, provider_keys, include_played=False, page_size=200):
    parsed_keys = [parsed for key in provider_keys if (parsed := _parse_series_provider_key(key))]
    if not parsed_keys:
        return [], None

    items = []
    seen_ids = set()
    series_cache = {}
    season_cache = {}
    server_label = server.get("name") or server.get("alias") or server.get("id") or "server"

    for index, parsed in enumerate(parsed_keys, start=1):
        provider_token = f"{parsed['provider']}.{parsed['provider_id']}"
        series_items = series_cache.get(provider_token)
        if series_items is None:
            logger.info(
                "[Emby Sync] series lookup %s/%s token=%s server=%s user=%s",
                index,
                len(parsed_keys),
                provider_token,
                server_label,
                user_id,
            )
            params = {
                "Recursive": "true",
                "Fields": "ProviderIds,Name,SortName",
                "IncludeItemTypes": "Series",
                "AnyProviderIdEquals": provider_token,
            }
            series_items, err = _fetch_emby_items_paged(server, user_id, params, page_size=page_size)
            if err:
                return [], err
            series_cache[provider_token] = series_items

        for series in series_items:
            series_id = series.get("Id")
            if not series_id:
                continue
            season_key = (series_id, parsed["season"])
            episode_items = season_cache.get(season_key)
            if episode_items is None:
                params = {
                    "UserId": user_id,
                    "Season": parsed["season"],
                    "Fields": USER_ITEM_FIELDS,
                }
                success, payload = _call_emby_api(server, f"Shows/{series_id}/Episodes", params=params)
                if not success:
                    return [], payload
                if not isinstance(payload, dict):
                    return [], "Risposta Episodes inattesa"
                episode_items = payload.get("Items") or []
                if not isinstance(episode_items, list):
                    return [], "Risposta Episodes inattesa"
                season_cache[season_key] = episode_items

            for episode in episode_items:
                if str(episode.get("IndexNumber") or "") != parsed["episode"]:
                    continue
                if str(episode.get("ParentIndexNumber") or "") != parsed["season"]:
                    continue
                if not include_played and (episode.get("UserData") or {}).get("Played"):
                    continue
                item_id = episode.get("Id")
                if item_id and item_id not in seen_ids:
                    episode.setdefault("SeriesProviderIds", {})[parsed["provider"]] = parsed["provider_id"]
                    items.append(episode)
                    seen_ids.add(item_id)

    return items, None


def _fetch_emby_items_by_provider_ids(
    server,
    user_id,
    provider_keys,
    include_played=False,
    page_size=200,
    include_item_types="Movie,Episode",
):
    """
    Fetch items on target server by provider IDs using AnyProviderIdEquals.
    provider_keys: list of strings like "tmdb:123", "imdb:tt123".
    """
    if not user_id:
        return [], "User ID mancante"

    if not provider_keys:
        return [], None

    series_keys = [key for key in provider_keys if _parse_series_provider_key(str(key))]
    tokens = []
    for key in provider_keys:
        token = _format_provider_token(key)
        if token:
            tokens.append(token)

    items = []
    seen_ids = set()

    if tokens:
        chunks = list(_chunk_list(tokens, 100))
        for index, chunk in enumerate(chunks, start=1):
            if len(chunks) > 1:
                logger.info(
                    "[Emby Sync] provider lookup chunk %s/%s keys=%s server=%s user=%s",
                    index,
                    len(chunks),
                    len(chunk),
                    server.get("name") or server.get("alias") or server.get("id") or "server",
                    user_id,
                )
            params = {
                "Recursive": "true",
                "Fields": USER_ITEM_FIELDS,
                "IncludeItemTypes": include_item_types,
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

    series_items, err = _fetch_emby_items_by_series_provider_keys(
        server,
        user_id,
        series_keys,
        include_played=include_played,
        page_size=page_size,
    )
    if err:
        return [], err

    for it in series_items:
        it_id = it.get("Id")
        if it_id and it_id not in seen_ids:
            items.append(it)
            seen_ids.add(it_id)

    return items, None


def _fetch_emby_items_by_safe_fallback(server, user_id, source_item, page_size=100):
    """Find a target item by a conservative title/year/runtime signature."""
    if not user_id:
        return [], "User ID mancante"

    signature = get_safe_fallback_signature(source_item)
    if not signature:
        return [], None

    search_terms = []
    if signature["type"] == "Movie":
        search_terms.extend([source_item.get("Name"), source_item.get("OriginalTitle")])
    elif signature["type"] == "Episode":
        search_terms.extend([source_item.get("SeriesName"), source_item.get("Name")])

    matches = []
    seen_ids = set()
    for raw_term in search_terms:
        term = str(raw_term or "").strip()
        if not term:
            continue
        params = {
            "Recursive": "true",
            "SearchTerm": term,
            "Fields": USER_ITEM_FIELDS,
            "IncludeItemTypes": signature["type"],
        }
        candidates, err = _fetch_emby_items_paged(
            server,
            user_id,
            params,
            page_size=page_size,
            label="fallback_match"
        )
        if err:
            return [], err
        for candidate in candidates:
            item_id = candidate.get("Id")
            if not item_id or item_id in seen_ids:
                continue
            if matches_safe_fallback_signature(candidate, signature):
                matches.append(candidate)
                seen_ids.add(item_id)

    if len(matches) > 1:
        return [], f"Match fallback ambiguo: {len(matches)} risultati"

    return matches, None


def _mark_emby_item_played(server, user_id, item_id, date_played=None):
    """
    Segna un elemento come visto (Played).
    """
    if not user_id or not item_id:
        return False, "ID mancanti"

    params = {}
    if date_played:
        formatted_date = _format_emby_date_played(date_played)
        if formatted_date:
            params["DatePlayed"] = formatted_date

    success, payload = _call_emby_api(
        server,
        f"Users/{user_id}/PlayedItems/{item_id}",
        method="POST",
        params=params
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


def _set_emby_item_resume(server, user_id, item_id, position_ticks, last_played_date=None, preserve_played=False):
    """
    Imposta la posizione di ripresa (resume) per un item.
    """
    if not user_id or not item_id:
        return False, "ID mancanti"
    if position_ticks is None:
        return False, "Resume position mancante"

    params = {"PlaybackPositionTicks": int(position_ticks)}
    if last_played_date:
        params["LastPlayedDate"] = last_played_date
    if preserve_played:
        params["Played"] = True
    success, payload = _call_emby_api(
        server,
        f"Users/{user_id}/Items/{item_id}/UserData",
        method="POST",
        json_payload=params
    )
    return success, payload


def _set_emby_item_hide_from_resume(server, user_id, item_id, hide=True):
    """
    Imposta o rimuove lo stato nascosto dalla lista Continua a guardare.
    """
    if not user_id or not item_id:
        return False, "ID mancanti"

    success, payload = _call_emby_api(
        server,
        f"Users/{user_id}/Items/{item_id}/HideFromResume",
        method="POST",
        params={"Hide": "true" if hide else "false"}
    )
    return success, payload


def _set_emby_item_favorite(server, user_id, item_id, is_favorite=True):
    """
    Imposta o rimuove il preferito per un item utente.
    """
    if not user_id or not item_id:
        return False, "ID mancanti"

    method = "POST" if is_favorite else "DELETE"
    success, payload = _call_emby_api(
        server,
        f"Users/{user_id}/FavoriteItems/{item_id}",
        method=method
    )
    return success, payload


def _fetch_emby_user_playlists(server, user_id):
    """
    Recupera le playlist visibili per l'utente.
    """
    if not user_id:
        return [], "User ID mancante"

    params = {
        "Recursive": "true",
        "IncludeItemTypes": "Playlist",
        "Fields": "ProviderIds,UserData,Name,SortName"
    }
    return _fetch_emby_items_paged(server, user_id, params, label="playlists")


def _fetch_emby_playlist_items(server, user_id, playlist_id):
    """
    Recupera gli item di una playlist nell'ordine restituito da Emby.
    """
    if not user_id or not playlist_id:
        return [], "ID mancanti"

    params = {
        "ParentId": playlist_id,
        "Fields": USER_ITEM_FIELDS,
        "IncludeItemTypes": "Movie,Episode",
    }
    return _fetch_emby_items_paged(server, user_id, params, label="playlist_items")


def _create_emby_playlist(server, user_id, name, item_ids=None):
    """
    Crea una playlist Emby per l'utente. Se possibile, aggiunge gli item iniziali in ordine.
    """
    if not user_id or not name:
        return False, "Dati playlist mancanti"

    params = {
        "Name": name,
        "UserId": user_id,
    }
    if item_ids:
        params["Ids"] = ",".join(str(item_id) for item_id in item_ids if item_id)

    success, payload = _call_emby_api(server, "Playlists", method="POST", params=params)
    if success:
        return success, payload

    # Some Emby builds expect a JSON body for playlist creation.
    json_payload = {
        "Name": name,
        "UserId": user_id,
        "Ids": [str(item_id) for item_id in (item_ids or []) if item_id],
    }
    return _call_emby_api(server, "Playlists", method="POST", json_payload=json_payload)


def _add_emby_playlist_items(server, user_id, playlist_id, item_ids):
    """
    Aggiunge item a una playlist, mantenendo l'ordine della lista passata.
    """
    if not user_id or not playlist_id:
        return False, "ID mancanti"
    ids = [str(item_id) for item_id in (item_ids or []) if item_id]
    if not ids:
        return True, {}

    params = {
        "UserId": user_id,
        "Ids": ",".join(ids),
    }
    success, payload = _call_emby_api(
        server,
        f"Playlists/{playlist_id}/Items",
        method="POST",
        params=params
    )
    if success:
        return success, payload

    json_payload = {"UserId": user_id, "Ids": ids}
    return _call_emby_api(
        server,
        f"Playlists/{playlist_id}/Items",
        method="POST",
        json_payload=json_payload
    )


def _remove_emby_playlist_entries(server, user_id, playlist_id, entry_ids):
    """
    Rimuove righe da una playlist quando Emby espone i PlaylistItemId.
    """
    if not user_id or not playlist_id:
        return False, "ID mancanti"
    ids = [str(entry_id) for entry_id in (entry_ids or []) if entry_id]
    if not ids:
        return True, {}

    params = {
        "UserId": user_id,
        "EntryIds": ",".join(ids),
    }
    success, payload = _call_emby_api(
        server,
        f"Playlists/{playlist_id}/Items",
        method="DELETE",
        params=params
    )
    if success:
        return success, payload

    json_payload = {"UserId": user_id, "EntryIds": ids}
    return _call_emby_api(
        server,
        f"Playlists/{playlist_id}/Items",
        method="DELETE",
        json_payload=json_payload
    )


def _delete_emby_playlist(server, user_id, playlist_id):
    """
    Elimina una playlist Emby intera.
    """
    if not user_id or not playlist_id:
        return False, "ID mancanti"

    success, payload = _call_emby_api(
        server,
        f"Items/{playlist_id}",
        method="DELETE",
        params={"UserId": user_id},
    )
    if success:
        return success, payload

    return _call_emby_api(
        server,
        f"Items/{playlist_id}",
        method="DELETE",
    )
