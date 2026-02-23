import logging
import json
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional, Tuple, Callable

from emby_runtime.api_clients import _fetch_emby_libraries
from emby_libraries.grouping import group_libraries
from core.utils import get_emby_servers

logger = logging.getLogger(__name__)

USER_SETTINGS_SCHEMA_VERSION = 1

USER_SETTINGS_SCHEMA = [
    {
        "id": "profile",
        "label": "Profilo",
        "column": "left",
        "policy": [
            {"key": "IsAdministrator", "label": "Amministratore", "type": "bool"},
            {"key": "EnableUserPreferenceAccess", "label": "Consenti modifica preferenze", "type": "bool"},
            {"key": "AuthenticationProviderId", "label": "Provider autenticazione", "type": "text"}
        ],
        "config": []
    },
    {
        "id": "access",
        "label": "Accesso",
        "column": "left",
        "policy": [
            {"key": "IsDisabled", "label": "Account disabilitato", "type": "bool"},
            {"key": "IsHidden", "label": "Nascondi utente", "type": "bool"},
            {"key": "IsHiddenRemotely", "label": "Nascondi da remoto", "type": "bool"},
            {"key": "IsHiddenFromUnusedDevices", "label": "Nascondi da dispositivi inutilizzati", "type": "bool"},
            {"key": "EnablePublicSharing", "label": "Condivisione pubblica", "type": "bool"},
            {"key": "EnableRemoteControlOfOtherUsers", "label": "Controllo remoto altri utenti", "type": "bool"},
            {"key": "EnableSharedDeviceControl", "label": "Controllo dispositivi condivisi", "type": "bool"},
            {"key": "AllowCameraUpload", "label": "Consenti upload fotocamera", "type": "bool"},
            {"key": "AllowSharingPersonalItems", "label": "Condivisione elementi personali", "type": "bool"},
            {"key": "AllowTagOrRating", "label": "Consenti tag/valutazioni", "type": "bool"},
            {"key": "EnableAllDevices", "label": "Tutti i dispositivi", "type": "bool"},
            {"key": "EnabledDevices", "label": "Dispositivi abilitati (uno per riga)", "type": "list"},
            {"key": "EnableAllChannels", "label": "Tutti i canali", "type": "bool"},
            {"key": "EnabledChannels", "label": "Canali abilitati (uno per riga)", "type": "list"},
            {"key": "EnableMediaPlayback", "label": "Consenti riproduzione media", "type": "bool"},
            {"key": "EnableAudioPlaybackTranscoding", "label": "Transcoding audio", "type": "bool"},
            {"key": "EnableVideoPlaybackTranscoding", "label": "Transcoding video", "type": "bool"},
            {"key": "EnablePlaybackRemuxing", "label": "Remuxing", "type": "bool"},
            {"key": "EnableMediaConversion", "label": "Conversione media", "type": "bool"},
            {"key": "EnableSyncTranscoding", "label": "Transcoding Sync", "type": "bool"},
            {"key": "EnableContentDeletion", "label": "Consenti eliminazione contenuti", "type": "bool"},
            {"key": "EnableContentDeletionFromFolders", "label": "Cartelle eliminabili (uno per riga)", "type": "list"},
            {"key": "EnableSubtitleDownloading", "label": "Download sottotitoli", "type": "bool"},
            {"key": "EnableSubtitleManagement", "label": "Gestione sottotitoli", "type": "bool"},
            {"key": "EnableLiveTvAccess", "label": "Accesso Live TV", "type": "bool"},
            {"key": "EnableLiveTvManagement", "label": "Gestione Live TV", "type": "bool"},
            {"key": "SimultaneousStreamLimit", "label": "Limite stream simultanei", "type": "int"},
            {"key": "RemoteClientBitrateLimit", "label": "Limite bitrate remoto (Kbps)", "type": "int"},
            {"key": "AutoRemoteQuality", "label": "Qualità remota automatica", "type": "int"},
            {"key": "RestrictedFeatures", "label": "Funzionalità limitate (una per riga)", "type": "list"},
            {"key": "InvalidLoginAttemptCount", "label": "Tentativi login non validi", "type": "int"},
            {"key": "LoginAttemptsBeforeLockout", "label": "Tentativi prima blocco", "type": "int"}
        ],
        "config": []
    },
    {
        "id": "parental",
        "label": "Controllo parentale",
        "column": "left",
        "policy": [
            {"key": "MaxParentalRating", "label": "Rating massimo", "type": "int"},
            {
                "key": "BlockUnratedItems",
                "label": "Blocca non classificati",
                "type": "multiselect",
                "options": [
                    {"value": "Movie", "label": "Film"},
                    {"value": "Trailer", "label": "Trailer"},
                    {"value": "Series", "label": "Serie"},
                    {"value": "Music", "label": "Musica"},
                    {"value": "Book", "label": "Libri"},
                    {"value": "LiveTvChannel", "label": "Canali Live TV"},
                    {"value": "LiveTvProgram", "label": "Programmi Live TV"},
                    {"value": "ChannelContent", "label": "Contenuti canale"},
                    {"value": "Other", "label": "Altro"}
                ]
            },
            {"key": "BlockedTags", "label": "Tag bloccati (uno per riga)", "type": "list"},
            {"key": "IncludeTags", "label": "Tag consentiti (uno per riga)", "type": "list"},
            {"key": "IsTagBlockingModeInclusive", "label": "Modalità inclusiva tag", "type": "bool"},
            {"key": "ExcludedSubFolders", "label": "Sottocartelle escluse (una per riga)", "type": "list"},
            {
                "key": "AccessSchedules",
                "label": "Fasce orarie accesso",
                "type": "schedule",
                "options": [
                    {"value": "Sunday", "label": "Domenica"},
                    {"value": "Monday", "label": "Lunedì"},
                    {"value": "Tuesday", "label": "Martedì"},
                    {"value": "Wednesday", "label": "Mercoledì"},
                    {"value": "Thursday", "label": "Giovedì"},
                    {"value": "Friday", "label": "Venerdì"},
                    {"value": "Saturday", "label": "Sabato"},
                    {"value": "Everyday", "label": "Tutti i giorni"},
                    {"value": "Weekday", "label": "Feriali"},
                    {"value": "Weekend", "label": "Weekend"}
                ]
            }
        ],
        "config": []
    },
    {
        "id": "libraries",
        "label": "Librerie",
        "column": "right",
        "libraries": True,
        "policy": [],
        "config": []
    },
    {
        "id": "display",
        "label": "Schermo",
        "column": "right",
        "policy": [],
        "config": [
            {"key": "OrderedViews", "label": "Ordinamento viste", "type": "library_order"},
            {"key": "LatestItemsExcludes", "label": "Escludi da Ultimi", "type": "library_multi"},
            {"key": "MyMediaExcludes", "label": "Escludi da I miei media", "type": "library_multi"},
            {"key": "GroupedFolders", "label": "Raggruppa cartelle", "type": "bool"},
            {"key": "ShowParentImages", "label": "Mostra immagini parent", "type": "bool"},
            {"key": "ShowUpdateCheckBox", "label": "Mostra aggiornamento librerie", "type": "bool"}
        ]
    },
    {
        "id": "home",
        "label": "Pagina Home",
        "column": "right",
        "policy": [],
        "config": [
            {"key": "HidePlayedInLatest", "label": "Nascondi visti in Ultimi", "type": "bool"},
            {"key": "HidePlayedInMoreLikeThis", "label": "Nascondi visti in Simili", "type": "bool"},
            {"key": "HidePlayedInSuggestions", "label": "Nascondi visti in Suggerimenti", "type": "bool"},
            {"key": "DisplayMissingEpisodes", "label": "Mostra episodi mancanti", "type": "bool"}
        ]
    },
    {
        "id": "playback_prefs",
        "label": "Riproduzione",
        "column": "right",
        "policy": [],
        "config": [
            {"key": "AudioLanguagePreference", "label": "Lingua audio predefinita", "type": "text"},
            {"key": "PlayDefaultAudioTrack", "label": "Usa traccia audio predefinita", "type": "bool"},
            {"key": "RememberAudioSelections", "label": "Ricorda scelta audio", "type": "bool"},
            {"key": "EnableNextEpisodeAutoPlay", "label": "Autoplay prossimo episodio", "type": "bool"},
            {"key": "ResumeRewindSeconds", "label": "Secondi riavvolgimento resume", "type": "int"},
            {
                "key": "IntroSkipMode",
                "label": "Skip intro",
                "type": "select",
                "options": [
                    {"value": "ShowButton", "label": "Mostra pulsante"},
                    {"value": "AutoSkip", "label": "Auto"},
                    {"value": "None", "label": "Mai"}
                ]
            }
        ]
    },
    {
        "id": "subtitles",
        "label": "Sottotitoli",
        "column": "right",
        "policy": [],
        "config": [
            {"key": "SubtitleLanguagePreference", "label": "Lingua sottotitoli predefinita", "type": "text"},
            {"key": "SubtitlePlayDefault", "label": "Sottotitoli predefiniti", "type": "bool"},
            {
                "key": "SubtitleMode",
                "label": "Modalità sottotitoli",
                "type": "select",
                "options": [
                    {"value": "Default", "label": "Default"},
                    {"value": "Always", "label": "Sempre"},
                    {"value": "Smart", "label": "Smart"},
                    {"value": "OnlyForced", "label": "Solo forzati"},
                    {"value": "HearingImpaired", "label": "Non udenti"},
                    {"value": "None", "label": "Mai"}
                ]
            },
            {"key": "RememberSubtitleSelections", "label": "Ricorda scelta sottotitoli", "type": "bool"}
        ]
    }
]

SETTINGS_POLICY_FIELDS = {
    field["key"]
    for category in USER_SETTINGS_SCHEMA
    for field in category.get("policy", [])
}

SETTINGS_CONFIG_FIELDS = {
    field["key"]
    for category in USER_SETTINGS_SCHEMA
    for field in category.get("config", [])
}

SETTINGS_LIST_FIELDS = {
    field["key"]
    for category in USER_SETTINGS_SCHEMA
    for field in category.get("policy", []) + category.get("config", [])
    if field.get("type") in ("list", "multiselect", "library_multi", "library_order")
}

SETTINGS_JSON_FIELDS = {
    field["key"]
    for category in USER_SETTINGS_SCHEMA
    for field in category.get("policy", []) + category.get("config", [])
    if field.get("type") in ("json", "schedule")
}


class SettingsManager:
    def __init__(
        self,
        storage,
        config: Dict[str, Any],
        get_server_by_id: Callable[[str], Optional[Dict[str, Any]]],
        get_group_users: Callable[[str], List[Tuple[str, str, Optional[str]]]],
        fetch_user_details: Callable[[Dict[str, Any], str], Tuple[Optional[Dict[str, Any]], Optional[str]]],
        update_user_policy: Callable[[Dict[str, Any], str, Dict[str, Any]], Tuple[bool, Optional[str]]],
        update_user_config: Callable[[Dict[str, Any], str, Dict[str, Any]], Tuple[bool, Optional[str]]],
    ):
        self.storage = storage
        self.config = config
        self._get_server_by_id = get_server_by_id
        self._get_group_users = get_group_users
        self._fetch_user_details = fetch_user_details
        self._update_user_policy = update_user_policy
        self._update_user_config = update_user_config

    def settings_group_key(self, group_id: str) -> str:
        return f"emby_group_settings:{group_id}"

    def settings_user_key(self, server_id: str, user_id: str) -> str:
        return f"emby_user_settings:{server_id}:{user_id}"

    def load_settings_entry(self, key: str) -> Optional[Dict[str, Any]]:
        entry = self.storage.get_key_value(key)
        if not isinstance(entry, dict):
            return None
        settings = entry.get("settings")
        if not isinstance(settings, dict):
            return None
        return entry

    def _save_settings_entry(self, key: str, settings: Dict[str, Any]) -> Dict[str, Any]:
        payload = {
            "settings": settings,
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "schema_version": USER_SETTINGS_SCHEMA_VERSION
        }
        self.storage.set_key_value(key, payload)
        return payload

    def _library_group_key(self, collection_type: str, group_name: str) -> str:
        return f"{collection_type}::{group_name}".lower()

    def _build_library_group_index(
        self
    ) -> Tuple[
        List[Dict[str, Any]],
        Dict[str, Dict[str, List[str]]],
        Dict[str, Dict[str, Any]],
        Dict[str, Dict[str, str]]
    ]:
        servers = get_emby_servers(self.config, enabled_only=True)
        all_libraries: Dict[str, Any] = {}
        for server in servers:
            if not server.get("enabled"):
                continue
            server_id = server.get("id")
            if not server_id:
                continue
            libraries, error = _fetch_emby_libraries(server)
            all_libraries[server_id] = {
                "ok": error is None,
                "libraries": libraries,
                "error": error,
                "name": server.get("name"),
                "alias": server.get("alias"),
                "original_name": server.get("original_name"),
                "icon": server.get("icon") or "fa-server",
                "icon_style": server.get("icon_style") or "solid",
                "icon_color": server.get("icon_color") or "#3b82f6"
            }

        associations = {}
        try:
            associations = self.storage.load_library_associations()
        except Exception:
            associations = {}
        grouped = group_libraries(all_libraries, associations)
        index: Dict[str, Dict[str, List[str]]] = {}
        membership: Dict[str, Dict[str, str]] = {}
        for group in grouped:
            group_name = group.get("group_name") or ""
            collection_type = group.get("collection_type") or ""
            group_key = self._library_group_key(collection_type, group_name)
            for lib in group.get("libraries", []):
                server_id = str(lib.get("server_id") or "")
                library_id = lib.get("library_id")
                if not server_id or not library_id:
                    continue
                lib_id = str(library_id)
                index.setdefault(group_key, {}).setdefault(server_id, []).append(lib_id)
                membership.setdefault(server_id, {})[lib_id] = group_key
        return grouped, index, all_libraries, membership

    def _normalize_settings_payload(self, settings: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        if not isinstance(settings, dict):
            settings = {}
        policy_raw = settings.get("policy")
        if not isinstance(policy_raw, dict):
            policy_raw = {}
        config_raw = settings.get("config")
        if not isinstance(config_raw, dict):
            config_raw = {}
        libraries_raw = settings.get("libraries")
        if not isinstance(libraries_raw, dict):
            libraries_raw = {}

        def _coerce_list(value: Any) -> List[str]:
            if value is None:
                return []
            if isinstance(value, list):
                return [str(x) for x in value if x is not None and str(x).strip() != ""]
            if isinstance(value, str):
                parts = [p.strip() for p in value.replace("\n", ",").split(",")]
                return [p for p in parts if p]
            return []

        def _coerce_json(value: Any) -> Any:
            if value is None:
                return []
            if isinstance(value, (list, dict)):
                return value
            if isinstance(value, str):
                try:
                    return json.loads(value)
                except Exception:
                    return value
            return value

        policy = {}
        for k, v in policy_raw.items():
            if k not in SETTINGS_POLICY_FIELDS or v is None:
                continue
            if k in SETTINGS_LIST_FIELDS:
                policy[k] = _coerce_list(v)
            elif k in SETTINGS_JSON_FIELDS:
                policy[k] = _coerce_json(v)
            else:
                policy[k] = v

        config = {}
        for k, v in config_raw.items():
            if k not in SETTINGS_CONFIG_FIELDS or v is None:
                continue
            if k in SETTINGS_LIST_FIELDS:
                config[k] = _coerce_list(v)
            elif k in SETTINGS_JSON_FIELDS:
                config[k] = _coerce_json(v)
            else:
                config[k] = v

        mode = libraries_raw.get("mode") if isinstance(libraries_raw.get("mode"), str) else "all"
        if mode not in ("all", "custom"):
            mode = "all"
        groups_raw = libraries_raw.get("groups")
        if not isinstance(groups_raw, dict):
            groups_raw = {}
        groups = {str(k).lower(): bool(v) for k, v in groups_raw.items()}

        items_raw = libraries_raw.get("items")
        if not isinstance(items_raw, list):
            items_raw = []
        items = [str(x) for x in items_raw if x]

        return {"policy": policy, "config": config, "libraries": {"mode": mode, "groups": groups, "items": items}}

    def settings_equal(self, left: Dict[str, Any], right: Dict[str, Any]) -> bool:
        left_norm = self._normalize_settings_payload(left)
        right_norm = self._normalize_settings_payload(right)
        left_norm.get("libraries", {}).pop("items", None)
        right_norm.get("libraries", {}).pop("items", None)
        return left_norm == right_norm

    def _derive_enabled_ids_from_groups(
        self,
        groups: Dict[str, bool],
        library_index: Dict[str, Dict[str, List[str]]],
        server_id: str
    ) -> List[str]:
        enabled_ids: List[str] = []
        for group_key, enabled in (groups or {}).items():
            if not enabled:
                continue
            for lib_id in library_index.get(group_key, {}).get(server_id, []):
                enabled_ids.append(str(lib_id))
        return enabled_ids

    def _build_library_items(
        self,
        server_id: str,
        libraries_by_server: Dict[str, Dict[str, Any]],
        membership: Dict[str, Dict[str, str]]
    ) -> List[Dict[str, Any]]:
        payload = libraries_by_server.get(server_id) or {}
        libraries = payload.get("libraries") or []
        items: List[Dict[str, Any]] = []
        for lib in libraries:
            if not isinstance(lib, dict):
                continue
            lib_id = lib.get("id") or lib.get("library_id")
            if not lib_id:
                continue
            lib_id_str = str(lib_id)
            group_key = membership.get(server_id, {}).get(lib_id_str)
            alt_ids = set()
            if lib.get("folder_id"):
                alt_ids.add(str(lib.get("folder_id")))
            if lib.get("item_id"):
                alt_ids.add(str(lib.get("item_id")))
            if lib.get("guid"):
                alt_ids.add(str(lib.get("guid")))
            alt_ids.add(lib_id_str)
            items.append({
                "id": lib_id_str,
                "name": lib.get("name"),
                "collection_type": lib.get("collection_type") or "folder",
                "group_key": group_key,
                "is_grouped": bool(group_key),
                "alt_ids": sorted(alt_ids)
            })
        return items

    def _extract_settings_from_details(
        self,
        details: Dict[str, Any],
        server_id: str,
        library_index: Dict[str, Dict[str, List[str]]]
    ) -> Dict[str, Any]:
        policy = details.get("Policy") if isinstance(details, dict) else {}
        if not isinstance(policy, dict):
            policy = {}
        config = details.get("Configuration") if isinstance(details, dict) else {}
        if not isinstance(config, dict):
            config = {}
        policy_out = {k: policy.get(k) for k in SETTINGS_POLICY_FIELDS if k in policy}
        config_out = {k: config.get(k) for k in SETTINGS_CONFIG_FIELDS if k in config}

        libraries = {"mode": "all", "groups": {}, "items": []}

        def _normalize_enabled_folders(raw) -> List[str]:
            if not raw:
                return []
            items = []
            if isinstance(raw, dict):
                raw_list = list(raw.values())
            else:
                raw_list = raw if isinstance(raw, list) else [raw]
            for entry in raw_list:
                if isinstance(entry, dict):
                    for key in ("Id", "ItemId", "LibraryId", "Guid"):
                        value = entry.get(key)
                        if value:
                            items.append(str(value))
                            break
                else:
                    items.append(str(entry))
            return [x for x in items if x]
        if isinstance(policy, dict):
            enable_all = policy.get("EnableAllFolders")
            enabled_folders = policy.get("EnabledFolders") or policy.get("EnabledLibraryFolders") or policy.get("EnabledMediaFolders") or []
            enabled_folders = _normalize_enabled_folders(enabled_folders)
            if enable_all is False:
                libraries["mode"] = "custom"
                enabled_set = {str(x) for x in enabled_folders if x}
                libraries["items"] = sorted(enabled_set)
                groups: Dict[str, bool] = {}
                for group_key, servers in library_index.items():
                    lib_ids = servers.get(server_id) or []
                    if any(str(lib_id) in enabled_set for lib_id in lib_ids):
                        groups[group_key] = True
                libraries["groups"] = groups

        return {"policy": policy_out, "config": config_out, "libraries": libraries}

    def get_settings_schema(self) -> Dict[str, Any]:
        grouped, _, _, _ = self._build_library_group_index()
        library_groups = []
        for group in grouped:
            group_name = group.get("group_name") or ""
            collection_type = group.get("collection_type") or ""
            if not group_name or not collection_type:
                continue
            library_groups.append({
                "key": self._library_group_key(collection_type, group_name),
                "group_name": group_name,
                "collection_type": collection_type,
                "servers": group.get("servers") or []
            })
        return {
            "schema_version": USER_SETTINGS_SCHEMA_VERSION,
            "categories": USER_SETTINGS_SCHEMA,
            "library_groups": library_groups
        }

    def get_settings_info(
        self,
        group_id: Optional[str] = None,
        server_id: Optional[str] = None,
        user_id: Optional[str] = None
    ) -> Dict[str, Any]:
        _, library_index, libraries_by_server, membership = self._build_library_group_index()
        if group_id:
            entry = self.load_settings_entry(self.settings_group_key(group_id))
            if entry:
                settings = self._normalize_settings_payload(entry.get("settings") or {})
                links = self.storage.get_user_links(group_id=group_id)
                leader_link = next((link for link in links if link.get("is_leader")), None)
                if not leader_link and links:
                    leader_link = links[0]
                leader_server_id = leader_link["server_id"] if leader_link else None
                if leader_server_id:
                    if settings.get("libraries", {}).get("mode") == "custom":
                        if not settings.get("libraries", {}).get("items"):
                            items = self._derive_enabled_ids_from_groups(
                                settings.get("libraries", {}).get("groups") or {},
                                library_index,
                                leader_server_id
                            )
                            settings["libraries"]["items"] = items
                    library_items = self._build_library_items(leader_server_id, libraries_by_server, membership)
                else:
                    library_items = []
                return {
                    "ok": True,
                    "saved": True,
                    "group_id": group_id,
                    "settings": settings,
                    "updated_at": entry.get("updated_at"),
                    "from_emby": False,
                    "library_items": library_items
                }
            links = self.storage.get_user_links(group_id=group_id)
            leader_link = next((link for link in links if link.get("is_leader")), None)
            if not leader_link and links:
                leader_link = links[0]
            if leader_link:
                leader_server_id = leader_link["server_id"]
                leader_user_id = leader_link["user_id"]
                server = self._get_server_by_id(leader_server_id)
                if server:
                    details, err = self._fetch_user_details(server, leader_user_id)
                    if not err and details:
                        settings = self._extract_settings_from_details(details, leader_server_id, library_index)
                        library_items = self._build_library_items(leader_server_id, libraries_by_server, membership)
                        return {
                            "ok": True,
                            "saved": False,
                            "group_id": group_id,
                            "settings": settings,
                            "updated_at": None,
                            "from_emby": True,
                            "library_items": library_items
                        }
            return {"ok": True, "saved": False, "group_id": group_id, "settings": {}, "updated_at": None, "from_emby": False, "library_items": []}

        if not server_id or not user_id:
            return {"ok": False, "error": "Missing target"}
        entry = self.load_settings_entry(self.settings_user_key(server_id, user_id))
        if entry:
            settings = self._normalize_settings_payload(entry.get("settings") or {})
        else:
            settings = None
        server = self._get_server_by_id(server_id)
        if server:
            details, err = self._fetch_user_details(server, user_id)
            if not err and details:
                emby_settings = self._extract_settings_from_details(details, server_id, library_index)
                if settings is None:
                    settings = emby_settings
                    saved = False
                else:
                    settings["libraries"] = emby_settings.get("libraries") or {}
                    saved = True
                library_items = self._build_library_items(server_id, libraries_by_server, membership)
                return {
                    "ok": True,
                    "saved": saved,
                    "server_id": server_id,
                    "user_id": user_id,
                    "settings": settings,
                    "updated_at": entry.get("updated_at") if entry else None,
                    "from_emby": not saved,
                    "library_items": library_items
                }
        if settings is None:
            settings = {}
        return {"ok": True, "saved": bool(entry), "server_id": server_id, "user_id": user_id, "settings": settings, "updated_at": entry.get("updated_at") if entry else None, "from_emby": False, "library_items": []}

    def _apply_settings_to_user(
        self,
        server_id: str,
        user_id: str,
        settings: Dict[str, Any],
        library_index: Dict[str, Dict[str, List[str]]],
        libraries_by_server: Dict[str, Dict[str, Any]],
        preserve_non_group: bool = False
    ) -> Tuple[bool, bool]:
        server = self._get_server_by_id(server_id)
        if not server:
            return False, False
        details, err = self._fetch_user_details(server, user_id)
        if err or not details:
            return False, False

        policy = details.get("Policy") if isinstance(details, dict) else {}
        config = details.get("Configuration") if isinstance(details, dict) else {}
        if not isinstance(policy, dict):
            policy = {}
        if not isinstance(config, dict):
            config = {}

        norm = self._normalize_settings_payload(settings)
        for k, v in norm.get("policy", {}).items():
            policy[k] = v
        for k, v in norm.get("config", {}).items():
            config[k] = v

        libraries = norm.get("libraries") or {}
        mode = libraries.get("mode")
        groups = libraries.get("groups") or {}
        items = libraries.get("items") or []
        if mode == "all":
            policy["EnableAllFolders"] = True
            policy["EnabledFolders"] = []
        elif mode == "custom":
            if items:
                enabled_ids = [str(x) for x in items if x]
            else:
                enabled_ids = self._derive_enabled_ids_from_groups(groups, library_index, server_id)
            if preserve_non_group:
                server_payload = libraries_by_server.get(server_id) or {}
                libraries = server_payload.get("libraries") or []
                server_library_ids = {str(lib.get("id") or lib.get("library_id")) for lib in libraries if lib.get("id") or lib.get("library_id")}
                grouped_ids = set()
                for group_key in library_index:
                    grouped_ids.update(library_index.get(group_key, {}).get(server_id, []))
                grouped_ids = {str(x) for x in grouped_ids}
                non_group_ids = server_library_ids - grouped_ids
                if policy.get("EnableAllFolders") is True:
                    current_enabled = set(server_library_ids)
                else:
                    current_enabled = {str(x) for x in (policy.get("EnabledFolders") or [])}
                preserved = current_enabled.intersection(non_group_ids)
                enabled_ids = list(preserved.union(set(enabled_ids)))
            policy["EnableAllFolders"] = False
            policy["EnabledFolders"] = enabled_ids

        ok_p, _ = self._update_user_policy(server, user_id, policy)
        ok_c, _ = self._update_user_config(server, user_id, config)
        return ok_p, ok_c

    def update_user_settings(self, server_id: str, user_id: str, settings: Dict[str, Any]) -> Dict[str, Any]:
        _, library_index, libraries_by_server, _ = self._build_library_group_index()
        normalized = self._normalize_settings_payload(settings)
        items = normalized.get("libraries", {}).get("items") or []
        groups = normalized.get("libraries", {}).get("groups") or {}
        if items and not groups:
            enabled_set = {str(x) for x in items if x}
            derived_groups: Dict[str, bool] = {}
            for group_key, servers in library_index.items():
                lib_ids = servers.get(server_id) or []
                if any(str(lib_id) in enabled_set for lib_id in lib_ids):
                    derived_groups[group_key] = True
            normalized["libraries"]["groups"] = derived_groups
        ok_p, ok_c = self._apply_settings_to_user(server_id, user_id, normalized, library_index, libraries_by_server)
        if not ok_p or not ok_c:
            return {"ok": False, "error": "Update failed", "policy": ok_p, "config": ok_c}
        entry = self._save_settings_entry(self.settings_user_key(server_id, user_id), normalized)
        logger.info("[SETTINGS] Saved user settings: %s/%s", server_id, user_id)
        return {"ok": True, "updated_at": entry.get("updated_at")}

    def set_group_settings(self, group_id: str, settings: Dict[str, Any]) -> Dict[str, Any]:
        users = self._get_group_users(group_id)
        if not users:
            return {"ok": False, "error": "Group has no users", "group_id": group_id}
        _, library_index, libraries_by_server, _ = self._build_library_group_index()
        normalized = self._normalize_settings_payload(settings)
        normalized["libraries"]["items"] = []
        entry = self._save_settings_entry(self.settings_group_key(group_id), normalized)
        failures = []
        applied = 0
        for server_id, user_id, _ in users:
            ok_p, ok_c = self._apply_settings_to_user(
                server_id,
                user_id,
                normalized,
                library_index,
                libraries_by_server,
                preserve_non_group=True
            )
            if ok_p and ok_c:
                applied += 1
                self._save_settings_entry(self.settings_user_key(server_id, user_id), normalized)
            else:
                failures.append({"server_id": server_id, "user_id": user_id, "policy": ok_p, "config": ok_c})
        if failures:
            logger.error("[SETTINGS] Group update failed: %s", failures)
            return {"ok": False, "group_id": group_id, "applied": applied, "failed": failures}
        logger.info("[SETTINGS] Saved group settings: %s", group_id)
        return {"ok": True, "group_id": group_id, "applied": applied, "updated_at": entry.get("updated_at")}
