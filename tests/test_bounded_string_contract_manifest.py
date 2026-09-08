"""Fail closed when a bounded SQL string lacks an explicit input policy."""

from __future__ import annotations

from pathlib import Path
import re

from core import auth
from core.storage.storage_models import Base


# schema|table|policy|column:length,...
# Policies distinguish identities rejected at a boundary, external descriptions
# projected to a safe representation, values generated internally, and dormant
# schema retained without an active writer. Adding or resizing a VARCHAR must
# deliberately update this manifest and its boundary/projection canary.
_MANIFEST = """
storage|emby_collection_backdrops|request_reject|collection_id:50,mime_type:50
storage|emby_collection_definitions|request_reject|id:50
storage|emby_collection_posters|request_reject|collection_id:50,mime_type:50
storage|emby_group_passwords|request_reject|group_id:266
storage|emby_icon_bindings|request_reject|target_type:20,target_id:257,profile_id:36
storage|emby_icon_profiles|request_reject|id:36,label:255
storage|emby_icon_rules|request_reject|profile_id:36,column_key:100,mime_type:50
storage|emby_image_cache|upstream_project|cache_key:255,mime_type:100,image_hash:64
storage|emby_latest_cache_changes|upstream_project|cache_kind:20,kind:50,label:200,episode_title:500,quality:100,resolution:100,video_codec:100,audio_codec:100,audio_channels:50,container:50,bitrate:50,source_name:200,media_source_id:128
storage|emby_latest_cache_errors|generated_internal|cache_kind:20,server_id:36
storage|emby_latest_cache_items|upstream_project|cache_kind:20,item_type:20,server_id:36,item_id:128,signature:255,batch_id:255,title:500,original_title:500,series_name:500,season_name:500,episode_title:500,community_rating:50,official_rating:50,image_tag:255,tmdb_id:50,imdb_id:50,tvdb_id:50,trakt_id:100,library_id:128,library_name:500,server_name:255,server_icon:100,server_icon_color:50,server_icon_style:50,update_type:20,update_label:200,tmdb_rating:50,tmdb_votes:50,imdb_rating:50,imdb_votes:50,metacritic_rating:50,trakt_rating:50,trakt_votes:50
storage|emby_latest_cache_meta|generated_internal|cache_kind:20
storage|emby_latest_notification_deliveries|generated_internal|delivery_key:64,server_id:36,destination_key:257,status:20,claim_token:32
storage|emby_latest_progress|generated_internal|state:50
storage|emby_probe_blacklist|upstream_project|item_id:128,item_name:500,item_type:50,error_type:20,server_id:36,server_name:255,library_id:128,library_name:500,media_source_id:128,scope:20
storage|emby_probe_history|upstream_project|item_id:128,server_id:36,media_source_id:128,scope:20,name:500,library_name:500,status:20
storage|emby_probe_queue|upstream_project|item_id:128,server_id:36,media_source_id:128,scope:20,library_id:128,library_name:500,name:500,series_name:500,media_type:50,claim_token:32
storage|emby_probe_recent_scans|upstream_project|server_id:36,library_id:128,server_name:255,event_type:50,status:50
storage|emby_user_backups|request_reject|server_id:128,user_id:128,username:255,backup_type:50
storage|emby_user_creation_journal|request_reject|server_id:128,normalized_username:255,username:255,status:32
storage|emby_user_links|request_reject|server_id:128,user_id:128,group_id:255,username:255,link_key:257
storage|jellyseerr_requests|upstream_project|request_id:50,media_type:10,status:50,status_label:100,requested_by:255
storage|justwatch_cache|upstream_project|show_name:512
storage|key_value|request_reject|key:512
storage|library_associations|request_reject|server_id:128,library_id:128,library_name:500,group_name:500,collection_type:50
storage|library_group_order|request_reject|collection_type:50,group_name:500
storage|request_cache|inactive|request_id:50
storage|request_rule_entries|request_reject|request_id:50
storage|tab_order|inactive|page:50,tab_key:100
storage|workflow_executions|generated_internal|id:36,workflow_type:20,status:20,owner_id:36
storage|workflow_steps|generated_internal|workflow_id:36,step_id:20,status:20
auth|api_tokens|request_reject|name:120,token_hash:64,token_prefix:16
auth|audit_logs|upstream_project|username:80,action:120,ip_address:64,path:255,method:10,user_agent:255
auth|user_interface_preferences|request_reject|primary_navigation:20,secondary_navigation:20
auth|users|request_reject|username:80,password_hash:255,email:120,role:20
"""

# schema|table|policy|column,... (unbounded Text columns)
_TEXT_MANIFEST = """
storage|emby_group_passwords|generated_internal|password_enc
storage|emby_icon_rules|request_reject|icon_path
storage|emby_image_cache|generated_internal|image_url
storage|emby_latest_cache_changes|upstream_project|path,video_details,audio_details,audio_ita,audio_eng,audio_fra,audio_spa,audio_ger,audio_jpn,audio_langs,subtitle_langs
storage|emby_latest_cache_errors|upstream_project|message
storage|emby_latest_cache_items|upstream_project|overview,image_url,poster_url,backdrop_url,banner_url,thumb_url,logo_url,emby_url,tagline,tmdb_poster_url,tmdb_backdrop_url,tmdb_banner_url,tmdb_thumb_url
storage|emby_latest_notification_deliveries|request_reject|publication_key
storage|emby_latest_notification_deliveries|upstream_project|last_error
storage|emby_latest_progress|upstream_project|message
storage|emby_probe_blacklist|upstream_project|reason
storage|emby_probe_history|upstream_project|error_details
storage|emby_probe_queue|upstream_project|path
storage|workflow_executions|upstream_project|error
storage|workflow_steps|upstream_project|details
auth|api_tokens|generated_internal|scopes
auth|audit_logs|upstream_project|detail
auth|user_interface_preferences|generated_internal|navigation_order
"""

_POLICIES = {
    "request_reject",
    "upstream_project",
    "generated_internal",
    "inactive",
}

# Tables above use a compact default, while every mixed-origin column is
# overridden explicitly so the resulting policy remains column-specific.
_POLICY_OVERRIDES = {
    "storage.emby_collection_backdrops.mime_type": "generated_internal",
    "storage.emby_collection_posters.mime_type": "generated_internal",
    "storage.emby_icon_rules.mime_type": "generated_internal",
    "storage.emby_image_cache.cache_key": "request_reject",
    "storage.emby_image_cache.image_hash": "generated_internal",
    "storage.emby_latest_cache_changes.cache_kind": "generated_internal",
    "storage.emby_latest_cache_changes.media_source_id": "request_reject",
    "storage.emby_latest_cache_errors.server_id": "request_reject",
    "storage.emby_latest_cache_items.cache_kind": "generated_internal",
    "storage.emby_latest_cache_items.server_id": "request_reject",
    "storage.emby_latest_cache_items.item_id": "request_reject",
    "storage.emby_latest_cache_items.library_id": "request_reject",
    "storage.emby_latest_cache_items.signature": "generated_internal",
    "storage.emby_latest_cache_items.batch_id": "generated_internal",
    "storage.emby_latest_notification_deliveries.server_id": "request_reject",
    "storage.emby_latest_notification_deliveries.destination_key": "request_reject",
    "storage.emby_probe_blacklist.item_id": "request_reject",
    "storage.emby_probe_blacklist.server_id": "request_reject",
    "storage.emby_probe_blacklist.library_id": "request_reject",
    "storage.emby_probe_blacklist.media_source_id": "request_reject",
    "storage.emby_probe_blacklist.scope": "generated_internal",
    "storage.emby_probe_blacklist.item_type": "inactive",
    "storage.emby_probe_blacklist.server_name": "inactive",
    "storage.emby_probe_history.item_id": "request_reject",
    "storage.emby_probe_history.server_id": "request_reject",
    "storage.emby_probe_history.media_source_id": "request_reject",
    "storage.emby_probe_history.scope": "generated_internal",
    "storage.emby_probe_history.status": "generated_internal",
    "storage.emby_probe_queue.item_id": "request_reject",
    "storage.emby_probe_queue.server_id": "request_reject",
    "storage.emby_probe_queue.media_source_id": "request_reject",
    "storage.emby_probe_queue.library_id": "request_reject",
    "storage.emby_probe_queue.scope": "generated_internal",
    "storage.emby_probe_queue.claim_token": "generated_internal",
    "storage.emby_probe_recent_scans.server_id": "request_reject",
    "storage.emby_probe_recent_scans.library_id": "request_reject",
    "storage.emby_probe_recent_scans.server_name": "inactive",
    "storage.emby_probe_recent_scans.event_type": "inactive",
    "storage.emby_probe_recent_scans.status": "inactive",
    "storage.emby_user_backups.server_id": "request_reject",
    "storage.emby_user_backups.user_id": "request_reject",
    "storage.emby_user_backups.username": "upstream_project",
    "storage.emby_user_creation_journal.normalized_username": "generated_internal",
    "storage.emby_user_creation_journal.status": "generated_internal",
    "storage.emby_user_links.username": "request_reject",
    "storage.emby_user_links.link_key": "inactive",
    "storage.jellyseerr_requests.request_id": "request_reject",
    "storage.library_associations.library_name": "inactive",
    "storage.library_associations.collection_type": "inactive",
    "auth.api_tokens.token_hash": "generated_internal",
    "auth.api_tokens.token_prefix": "generated_internal",
    "auth.users.password_hash": "generated_internal",
}


def _manifest_contracts() -> tuple[dict[str, int], dict[str, str]]:
    lengths: dict[str, int] = {}
    policies: dict[str, str] = {}
    for line in _MANIFEST.strip().splitlines():
        schema, table, policy, columns = line.split("|", 3)
        assert policy in _POLICIES
        for item in columns.split(","):
            column, raw_length = item.split(":", 1)
            key = f"{schema}.{table}.{column}"
            assert key not in lengths
            lengths[key] = int(raw_length)
            policies[key] = _POLICY_OVERRIDES.get(key, policy)
    assert set(_POLICY_OVERRIDES) <= set(lengths)
    assert set(_POLICY_OVERRIDES.values()) <= _POLICIES
    return lengths, policies


def _schema_contracts() -> dict[str, int]:
    actual: dict[str, int] = {}
    for schema, metadata in (
        ("storage", Base.metadata),
        ("auth", auth.Base.metadata),
    ):
        for table in metadata.tables.values():
            for column in table.columns:
                length = getattr(column.type, "length", None)
                if length is not None:
                    actual[f"{schema}.{table.name}.{column.name}"] = int(length)
    return actual


def _text_manifest_contracts() -> dict[str, str]:
    contracts: dict[str, str] = {}
    for line in _TEXT_MANIFEST.strip().splitlines():
        schema, table, policy, columns = line.split("|", 3)
        assert policy in _POLICIES
        for column in columns.split(","):
            key = f"{schema}.{table}.{column}"
            assert key not in contracts
            contracts[key] = policy
    return contracts


def _schema_text_columns() -> set[str]:
    actual: set[str] = set()
    for schema, metadata in (
        ("storage", Base.metadata),
        ("auth", auth.Base.metadata),
    ):
        for table in metadata.tables.values():
            for column in table.columns:
                if column.type.__class__.__name__ == "Text":
                    actual.add(f"{schema}.{table.name}.{column.name}")
    return actual


def test_every_bounded_sql_string_has_an_exact_input_policy() -> None:
    expected, policies = _manifest_contracts()
    actual = _schema_contracts()

    assert actual == expected
    assert set(policies) == set(actual)


def test_every_unbounded_sql_text_has_an_explicit_input_policy() -> None:
    expected = _text_manifest_contracts()

    assert _schema_text_columns() == set(expected)


_KV_CALLER_COUNTS = {
    "core/operations.py": 2,
    "core/storage/storage_collections.py": 4,
    "core/storage/storage_probe.py": 2,
    "emby_collections/source_inventory.py": 2,
    "emby_runtime/transcode_guard_control.py": 3,
    "emby_runtime/transcode_guard_history.py": 6,
    "emby_users/dashboard_manager.py": 6,
    "emby_users/group_manager.py": 6,
    "emby_users/settings_presets.py": 8,
    "emby_users/settings_storage.py": 2,
    "emby_users/state_tracker.py": 4,
    "emby_users/user_lifecycle_manager.py": 5,
    "services/scheduler_occurrences.py": 4,
}


def test_key_value_callers_are_an_explicit_review_inventory() -> None:
    root = Path(__file__).resolve().parents[1]
    call_pattern = re.compile(
        r"\.(?:set_key_value|update_key_value|compare_and_set_key_values|"
        r"get_key_value|get_keys_by_prefix|delete_key)\("
    )
    actual = {
        path.relative_to(root).as_posix(): len(call_pattern.findall(source))
        for top_level in ("core", "emby_collections", "emby_runtime", "emby_users", "services", "search", "telegram", "web")
        for path in (root / top_level).rglob("*.py")
        if call_pattern.search(source := path.read_text(encoding="utf-8"))
    }

    assert actual == _KV_CALLER_COUNTS


def test_direct_key_value_row_writers_are_an_explicit_review_inventory() -> None:
    root = Path(__file__).resolve().parents[1]
    constructor = re.compile(r"KeyValueEntry\(")
    expected = {
        "core/storage/storage_collections.py": 3,
        "core/storage/storage_probe.py": 1,
    }
    actual = {
        path.relative_to(root).as_posix(): len(constructor.findall(source))
        for path in (root / "core" / "storage").rglob("*.py")
        if path.name != "storage_models.py"
        if constructor.search(source := path.read_text(encoding="utf-8"))
    }

    assert actual == expected
