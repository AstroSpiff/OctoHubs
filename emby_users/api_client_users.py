"""API client helpers for Emby user management (user CRUD)."""

from emby_runtime.api_clients import _call_emby_api


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


def _fetch_emby_user_display_preferences(server, user_id, prefs_id="usersettings", client="emby"):
    """
    Recupera le preferenze display/client dell'utente.

    Emby salva molte preferenze della UI in DisplayPreferences.CustomPrefs,
    separate da UserPolicy e UserConfiguration.
    """
    if not user_id:
        return None, "User ID mancante"

    success, payload = _call_emby_api(
        server,
        f"DisplayPreferences/{prefs_id}",
        params={"UserId": user_id, "Client": client}
    )
    if success and isinstance(payload, dict):
        payload.setdefault("Id", prefs_id)
        payload.setdefault("Client", client)
        payload.setdefault("CustomPrefs", {})
        if not isinstance(payload["CustomPrefs"], dict):
            payload["CustomPrefs"] = {}
        return payload, None
    return None, payload


def _update_emby_user_display_preferences(server, user_id, preferences, prefs_id="usersettings", client="emby"):
    """
    Aggiorna le preferenze display/client dell'utente.
    """
    if not user_id or not isinstance(preferences, dict):
        return False, "Dati non validi"

    payload = dict(preferences)
    payload.setdefault("Id", prefs_id)
    payload.setdefault("Client", client)
    payload.setdefault("CustomPrefs", {})
    if not isinstance(payload["CustomPrefs"], dict):
        payload["CustomPrefs"] = {}

    success, response = _call_emby_api(
        server,
        f"DisplayPreferences/{prefs_id}",
        method="POST",
        params={"UserId": user_id, "Client": client},
        json_payload=payload
    )
    return success, response


def _fetch_emby_features(server):
    """
    Recupera le funzionalita installate esposte da Emby.

    UserPolicy.RestrictedFeatures usa questi ID per disabilitare singole
    funzionalita/plugin per utente.
    """
    success, payload = _call_emby_api(server, "Features")
    if not success:
        return [], payload

    items = payload if isinstance(payload, list) else payload.get("Items") if isinstance(payload, dict) else []
    if not isinstance(items, list):
        return [], "Formato risposta Features inatteso"

    features = []
    for entry in items:
        if not isinstance(entry, dict):
            continue
        feature_id = entry.get("Id") or entry.get("id")
        if not feature_id:
            continue
        features.append({
            "id": str(feature_id),
            "name": entry.get("Name") or entry.get("DisplayName") or str(feature_id),
            "feature_type": entry.get("FeatureType") or entry.get("featureType") or "",
        })
    features.sort(key=lambda item: (str(item.get("feature_type") or ""), str(item.get("name") or "").lower()))
    return features, None


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


def _delete_emby_user(server, user_id):
    """
    Deletes a user from the Emby server.
    """
    if not user_id:
        return False, "User ID mancante"

    success, payload = _call_emby_api(
        server,
        f"Users/{user_id}",
        method="DELETE"
    )
    return success, payload
