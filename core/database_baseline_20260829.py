"""Immutable DDL snapshot for the 2026-08-29 unified-schema baseline."""

from __future__ import annotations

import re
from typing import Any

from sqlalchemy import (
    ARRAY,
    BigInteger,
    Boolean,
    Column,
    DateTime,
    Index,
    Integer,
    JSON,
    LargeBinary,
    MetaData,
    String,
    Table,
    Text,
    UniqueConstraint,
)


_POSTGRES_STORAGE_TABLES = (
    (
        'app_settings',
        'CREATE TABLE app_settings (\n\tid INTEGER NOT NULL, \n\tdata JSON NOT NULL, \n\tupdated_at TIMESTAMP WITHOUT TIME ZONE, \n\tPRIMARY KEY (id)\n)',
        (
        ),
    ),
    (
        'emby_collection_backdrops',
        'CREATE TABLE emby_collection_backdrops (\n\tcollection_id VARCHAR(50) NOT NULL, \n\tmime_type VARCHAR(50), \n\tdata BYTEA, \n\tupdated_at TIMESTAMP WITHOUT TIME ZONE, \n\tPRIMARY KEY (collection_id)\n)',
        (
        ),
    ),
    (
        'emby_collection_definitions',
        'CREATE TABLE emby_collection_definitions (\n\tid VARCHAR(50) NOT NULL, \n\tdata JSON, \n\tupdated_at TIMESTAMP WITHOUT TIME ZONE, \n\tPRIMARY KEY (id)\n)',
        (
        ),
    ),
    (
        'emby_collection_posters',
        'CREATE TABLE emby_collection_posters (\n\tcollection_id VARCHAR(50) NOT NULL, \n\tmime_type VARCHAR(50), \n\tdata BYTEA, \n\tupdated_at TIMESTAMP WITHOUT TIME ZONE, \n\tPRIMARY KEY (collection_id)\n)',
        (
        ),
    ),
    (
        'emby_group_passwords',
        'CREATE TABLE emby_group_passwords (\n\tgroup_id VARCHAR(255) NOT NULL, \n\tpassword_enc TEXT NOT NULL, \n\tupdated_at TIMESTAMP WITHOUT TIME ZONE, \n\tPRIMARY KEY (group_id)\n)',
        (
        ),
    ),
    (
        'emby_icon_bindings',
        'CREATE TABLE emby_icon_bindings (\n\ttarget_type VARCHAR(20) NOT NULL, \n\ttarget_id VARCHAR(255) NOT NULL, \n\tprofile_id VARCHAR(36) NOT NULL, \n\tupdated_at TIMESTAMP WITHOUT TIME ZONE, \n\tPRIMARY KEY (target_type, target_id)\n)',
        (
            'CREATE INDEX ix_emby_icon_bindings_profile_id ON emby_icon_bindings (profile_id)',
        ),
    ),
    (
        'emby_icon_profiles',
        'CREATE TABLE emby_icon_profiles (\n\tid VARCHAR(36) NOT NULL, \n\tlabel VARCHAR(255) NOT NULL, \n\tis_group_profile BOOLEAN, \n\tupdated_at TIMESTAMP WITHOUT TIME ZONE, \n\tPRIMARY KEY (id)\n)',
        (
        ),
    ),
    (
        'emby_icon_rules',
        'CREATE TABLE emby_icon_rules (\n\tprofile_id VARCHAR(36) NOT NULL, \n\tcolumn_key VARCHAR(100) NOT NULL, \n\ticon_path TEXT, \n\timage_data BYTEA, \n\tmime_type VARCHAR(50), \n\tupdated_at TIMESTAMP WITHOUT TIME ZONE, \n\tPRIMARY KEY (profile_id, column_key)\n)',
        (
        ),
    ),
    (
        'emby_image_cache',
        'CREATE TABLE emby_image_cache (\n\tcache_key VARCHAR(255) NOT NULL, \n\timage_url TEXT NOT NULL, \n\tmime_type VARCHAR(100), \n\timage_data BYTEA, \n\timage_hash VARCHAR(64), \n\tcreated_at TIMESTAMP WITHOUT TIME ZONE, \n\texpires_at TIMESTAMP WITHOUT TIME ZONE, \n\tPRIMARY KEY (cache_key)\n)',
        (
        ),
    ),
    (
        'emby_latest_cache_changes',
        'CREATE TABLE emby_latest_cache_changes (\n\tid SERIAL NOT NULL, \n\tcache_kind VARCHAR(20), \n\tcache_item_id INTEGER, \n\tsort_index INTEGER, \n\tkind VARCHAR(50), \n\tlabel VARCHAR(200), \n\tseason_number INTEGER, \n\tepisode_number INTEGER, \n\tepisode_title VARCHAR(500), \n\tquality VARCHAR(100), \n\tresolution VARCHAR(100), \n\tvideo_codec VARCHAR(100), \n\taudio_codec VARCHAR(100), \n\taudio_channels VARCHAR(50), \n\tcontainer VARCHAR(50), \n\tbitrate VARCHAR(50), \n\tsource_name VARCHAR(200), \n\tpath TEXT, \n\tsize BIGINT, \n\tmedia_source_id VARCHAR(100), \n\tadded_at TIMESTAMP WITHOUT TIME ZONE, \n\tvideo_details TEXT, \n\taudio_details TEXT, \n\taudio_ita TEXT, \n\taudio_eng TEXT, \n\taudio_fra TEXT, \n\taudio_spa TEXT, \n\taudio_ger TEXT, \n\taudio_jpn TEXT, \n\taudio_langs TEXT, \n\tsubtitle_langs TEXT, \n\tcreated_at TIMESTAMP WITHOUT TIME ZONE, \n\tPRIMARY KEY (id)\n)',
        (
            'CREATE INDEX ix_emby_latest_cache_changes_cache_item_id ON emby_latest_cache_changes (cache_item_id)',
            'CREATE INDEX ix_emby_latest_cache_changes_cache_kind ON emby_latest_cache_changes (cache_kind)',
        ),
    ),
    (
        'emby_latest_cache_errors',
        'CREATE TABLE emby_latest_cache_errors (\n\tid SERIAL NOT NULL, \n\tcache_kind VARCHAR(20), \n\tserver_id VARCHAR(36), \n\tmessage TEXT NOT NULL, \n\tcreated_at TIMESTAMP WITHOUT TIME ZONE, \n\tPRIMARY KEY (id)\n)',
        (
            'CREATE INDEX ix_emby_latest_cache_errors_cache_kind ON emby_latest_cache_errors (cache_kind)',
            'CREATE INDEX ix_emby_latest_cache_errors_server_id ON emby_latest_cache_errors (server_id)',
        ),
    ),
    (
        'emby_latest_cache_items',
        'CREATE TABLE emby_latest_cache_items (\n\tid SERIAL NOT NULL, \n\tcache_kind VARCHAR(20) NOT NULL, \n\titem_type VARCHAR(20), \n\tserver_id VARCHAR(36), \n\titem_id VARCHAR(36), \n\tsignature VARCHAR(255), \n\tbatch_id VARCHAR(255), \n\ttitle VARCHAR(500), \n\toriginal_title VARCHAR(500), \n\tseries_name VARCHAR(500), \n\tseason_name VARCHAR(500), \n\tseason_number INTEGER, \n\tepisode_number INTEGER, \n\tepisode_title VARCHAR(500), \n\tyear INTEGER, \n\toverview TEXT, \n\tgenres VARCHAR[], \n\tcommunity_rating VARCHAR(50), \n\tofficial_rating VARCHAR(50), \n\truntime_minutes INTEGER, \n\tadded_at TIMESTAMP WITHOUT TIME ZONE, \n\tpremiere_date TIMESTAMP WITHOUT TIME ZONE, \n\tchild_count INTEGER, \n\tseason_count INTEGER, \n\tepisode_count INTEGER, \n\timage_tag VARCHAR(255), \n\timage_url TEXT, \n\tposter_url TEXT, \n\tbackdrop_url TEXT, \n\tbanner_url TEXT, \n\tthumb_url TEXT, \n\tlogo_url TEXT, \n\temby_url TEXT, \n\ttagline TEXT, \n\tstudios VARCHAR[], \n\tcast_members VARCHAR[], \n\tdirectors VARCHAR[], \n\tcreators VARCHAR[], \n\ttmdb_id VARCHAR(50), \n\timdb_id VARCHAR(50), \n\ttvdb_id VARCHAR(50), \n\ttrakt_id VARCHAR(100), \n\tlibrary_id VARCHAR(36), \n\tlibrary_name VARCHAR(500), \n\tserver_name VARCHAR(255), \n\tserver_icon VARCHAR(100), \n\tserver_icon_color VARCHAR(50), \n\tserver_icon_style VARCHAR(50), \n\tupdate_type VARCHAR(20), \n\tupdate_label VARCHAR(200), \n\ttmdb_poster_url TEXT, \n\ttmdb_backdrop_url TEXT, \n\ttmdb_banner_url TEXT, \n\ttmdb_thumb_url TEXT, \n\ttmdb_rating VARCHAR(50), \n\ttmdb_votes VARCHAR(50), \n\timdb_rating VARCHAR(50), \n\timdb_votes VARCHAR(50), \n\tmetacritic_rating VARCHAR(50), \n\ttrakt_rating VARCHAR(50), \n\ttrakt_votes VARCHAR(50), \n\tomdb_fetched_at TIMESTAMP WITHOUT TIME ZONE, \n\ttrakt_fetched_at TIMESTAMP WITHOUT TIME ZONE, \n\tsort_ts TIMESTAMP WITHOUT TIME ZONE, \n\tPRIMARY KEY (id)\n)',
        (
            'CREATE INDEX ix_emby_latest_cache_items_batch_id ON emby_latest_cache_items (batch_id)',
            'CREATE INDEX ix_emby_latest_cache_items_cache_kind ON emby_latest_cache_items (cache_kind)',
            'CREATE INDEX ix_emby_latest_cache_items_item_id ON emby_latest_cache_items (item_id)',
            'CREATE INDEX ix_emby_latest_cache_items_item_type ON emby_latest_cache_items (item_type)',
            'CREATE INDEX ix_emby_latest_cache_items_server_id ON emby_latest_cache_items (server_id)',
            'CREATE INDEX ix_emby_latest_cache_items_signature ON emby_latest_cache_items (signature)',
            'CREATE INDEX ix_emby_latest_cache_items_sort_ts ON emby_latest_cache_items (sort_ts)',
            'CREATE INDEX ix_latest_cache_kind_server_type ON emby_latest_cache_items (cache_kind, server_id, item_type)',
            'CREATE INDEX ix_latest_cache_kind_sort ON emby_latest_cache_items (cache_kind, sort_ts)',
        ),
    ),
    (
        'emby_latest_cache_meta',
        'CREATE TABLE emby_latest_cache_meta (\n\tcache_kind VARCHAR(20) NOT NULL, \n\tupdated_at TIMESTAMP WITHOUT TIME ZONE, \n\t"limit" INTEGER NOT NULL, \n\tper_server_limit INTEGER NOT NULL, \n\tPRIMARY KEY (cache_kind)\n)',
        (
        ),
    ),
    (
        'emby_latest_progress',
        'CREATE TABLE emby_latest_progress (\n\tid SERIAL NOT NULL, \n\tstate VARCHAR(50), \n\ttotal INTEGER, \n\tcompleted INTEGER, \n\tmessage TEXT, \n\tstarted_at TIMESTAMP WITHOUT TIME ZONE, \n\tupdated_at TIMESTAMP WITHOUT TIME ZONE, \n\tPRIMARY KEY (id)\n)',
        (
        ),
    ),
    (
        'emby_latest_state_episodes',
        'CREATE TABLE emby_latest_state_episodes (\n\tserver_id VARCHAR(36) NOT NULL, \n\tseries_id VARCHAR(36) NOT NULL, \n\tepisode_key VARCHAR(255) NOT NULL, \n\tepisode_id VARCHAR(36), \n\tseason_number INTEGER, \n\tepisode_number INTEGER, \n\ttitle VARCHAR(500), \n\tlast_seen_at TIMESTAMP WITHOUT TIME ZONE, \n\tmedia_source_keys VARCHAR[], \n\tPRIMARY KEY (server_id, series_id, episode_key)\n)',
        (
            'CREATE INDEX ix_emby_latest_state_episodes_episode_id ON emby_latest_state_episodes (episode_id)',
            'CREATE INDEX ix_emby_latest_state_episodes_last_seen_at ON emby_latest_state_episodes (last_seen_at)',
        ),
    ),
    (
        'emby_latest_state_movies',
        'CREATE TABLE emby_latest_state_movies (\n\tserver_id VARCHAR(36) NOT NULL, \n\tstate_key VARCHAR(255) NOT NULL, \n\titem_id VARCHAR(36), \n\tsignature VARCHAR(255), \n\ttitle VARCHAR(500), \n\tyear INTEGER, \n\tlast_seen_at TIMESTAMP WITHOUT TIME ZONE, \n\tmedia_source_keys VARCHAR[], \n\tnotified BOOLEAN, \n\tnotified_at TIMESTAMP WITHOUT TIME ZONE, \n\tPRIMARY KEY (server_id, state_key)\n)',
        (
            'CREATE INDEX ix_emby_latest_state_movies_item_id ON emby_latest_state_movies (item_id)',
            'CREATE INDEX ix_emby_latest_state_movies_last_seen_at ON emby_latest_state_movies (last_seen_at)',
        ),
    ),
    (
        'emby_latest_state_series',
        'CREATE TABLE emby_latest_state_series (\n\tserver_id VARCHAR(36) NOT NULL, \n\tseries_id VARCHAR(36) NOT NULL, \n\ttitle VARCHAR(500), \n\tyear INTEGER, \n\tlast_seen_at TIMESTAMP WITHOUT TIME ZONE, \n\tseasons INTEGER[], \n\tnotified BOOLEAN, \n\tnotified_at TIMESTAMP WITHOUT TIME ZONE, \n\tPRIMARY KEY (server_id, series_id)\n)',
        (
            'CREATE INDEX ix_emby_latest_state_series_last_seen_at ON emby_latest_state_series (last_seen_at)',
        ),
    ),
    (
        'emby_latest_state_series_changes',
        'CREATE TABLE emby_latest_state_series_changes (\n\tid SERIAL NOT NULL, \n\tgroup_id INTEGER, \n\tsort_index INTEGER, \n\tkind VARCHAR(50), \n\tlabel VARCHAR(200), \n\tseason_number INTEGER, \n\tepisode_number INTEGER, \n\tepisode_title VARCHAR(500), \n\tquality VARCHAR(100), \n\tresolution VARCHAR(100), \n\tvideo_codec VARCHAR(100), \n\taudio_codec VARCHAR(100), \n\taudio_channels VARCHAR(50), \n\tcontainer VARCHAR(50), \n\tbitrate VARCHAR(50), \n\tsource_name VARCHAR(200), \n\tpath TEXT, \n\tsize BIGINT, \n\tmedia_source_id VARCHAR(100), \n\tadded_at TIMESTAMP WITHOUT TIME ZONE, \n\tvideo_details TEXT, \n\taudio_details TEXT, \n\taudio_ita TEXT, \n\taudio_eng TEXT, \n\taudio_fra TEXT, \n\taudio_spa TEXT, \n\taudio_ger TEXT, \n\taudio_jpn TEXT, \n\taudio_langs TEXT, \n\tsubtitle_langs TEXT, \n\tPRIMARY KEY (id)\n)',
        (
            'CREATE INDEX ix_emby_latest_state_series_changes_group_id ON emby_latest_state_series_changes (group_id)',
        ),
    ),
    (
        'emby_latest_state_series_groups',
        'CREATE TABLE emby_latest_state_series_groups (\n\tid SERIAL NOT NULL, \n\tserver_id VARCHAR(36), \n\tseries_id VARCHAR(36), \n\tsort_index INTEGER, \n\tupdate_type VARCHAR(20), \n\tupdate_label VARCHAR(200), \n\tbatch_id VARCHAR(255), \n\tadded_at TIMESTAMP WITHOUT TIME ZONE, \n\tPRIMARY KEY (id)\n)',
        (
            'CREATE INDEX ix_emby_latest_state_series_groups_series_id ON emby_latest_state_series_groups (series_id)',
            'CREATE INDEX ix_emby_latest_state_series_groups_server_id ON emby_latest_state_series_groups (server_id)',
        ),
    ),
    (
        'emby_probe_blacklist',
        'CREATE TABLE emby_probe_blacklist (\n\tid SERIAL NOT NULL, \n\titem_id VARCHAR(36), \n\titem_name VARCHAR(500), \n\titem_type VARCHAR(50), \n\treason TEXT, \n\terror_type VARCHAR(20), \n\tretry_count INTEGER, \n\tserver_id VARCHAR(36), \n\tserver_name VARCHAR(255), \n\tlibrary_id VARCHAR(36), \n\tlibrary_name VARCHAR(500), \n\tmedia_source_id VARCHAR(36), \n\tscope VARCHAR(20), \n\tfailed_at TIMESTAMP WITHOUT TIME ZONE, \n\tPRIMARY KEY (id)\n)',
        (
            'CREATE INDEX ix_emby_probe_blacklist_item_id ON emby_probe_blacklist (item_id)',
            'CREATE INDEX ix_emby_probe_blacklist_server_id ON emby_probe_blacklist (server_id)',
        ),
    ),
    (
        'emby_probe_history',
        'CREATE TABLE emby_probe_history (\n\tid SERIAL NOT NULL, \n\titem_id VARCHAR(36), \n\tserver_id VARCHAR(36), \n\tmedia_source_id VARCHAR(36), \n\tscope VARCHAR(20), \n\tname VARCHAR(500), \n\tlibrary_name VARCHAR(500), \n\tprocessed_at TIMESTAMP WITHOUT TIME ZONE NOT NULL, \n\tstatus VARCHAR(20), \n\terror_details TEXT, \n\tduration_ms INTEGER, \n\tPRIMARY KEY (id)\n)',
        (
            'CREATE INDEX ix_emby_probe_history_item_id ON emby_probe_history (item_id)',
            'CREATE INDEX ix_emby_probe_history_server_id ON emby_probe_history (server_id)',
        ),
    ),
    (
        'emby_probe_queue',
        'CREATE TABLE emby_probe_queue (\n\tid SERIAL NOT NULL, \n\titem_id VARCHAR(36), \n\tserver_id VARCHAR(36), \n\tmedia_source_id VARCHAR(36), \n\tscope VARCHAR(20), \n\tlibrary_id VARCHAR(36), \n\tlibrary_name VARCHAR(500), \n\tname VARCHAR(500), \n\tseries_name VARCHAR(500), \n\tseason_number INTEGER, \n\tepisode_number INTEGER, \n\tyear INTEGER, \n\tmedia_type VARCHAR(50), \n\tpath TEXT, \n\tadded_at TIMESTAMP WITHOUT TIME ZONE NOT NULL, \n\tPRIMARY KEY (id)\n)',
        (
            'CREATE INDEX ix_emby_probe_queue_item_id ON emby_probe_queue (item_id)',
            'CREATE INDEX ix_emby_probe_queue_server_id ON emby_probe_queue (server_id)',
        ),
    ),
    (
        'emby_probe_recent_scans',
        'CREATE TABLE emby_probe_recent_scans (\n\tid SERIAL NOT NULL, \n\tserver_id VARCHAR(36), \n\tlibrary_id VARCHAR(36), \n\tserver_name VARCHAR(255), \n\tevent_type VARCHAR(50), \n\tstatus VARCHAR(50), \n\tlast_scan_at TIMESTAMP WITHOUT TIME ZONE, \n\toldest_scanned_timestamp TIMESTAMP WITHOUT TIME ZONE, \n\tpayload JSON NOT NULL, \n\tPRIMARY KEY (id)\n)',
        (
            'CREATE INDEX ix_emby_probe_recent_scans_library_id ON emby_probe_recent_scans (library_id)',
            'CREATE INDEX ix_emby_probe_recent_scans_server_id ON emby_probe_recent_scans (server_id)',
        ),
    ),
    (
        'emby_user_backups',
        'CREATE TABLE emby_user_backups (\n\tid SERIAL NOT NULL, \n\tserver_id VARCHAR(36) NOT NULL, \n\tuser_id VARCHAR(36) NOT NULL, \n\tusername VARCHAR(255), \n\tbackup_type VARCHAR(50), \n\tdata JSON NOT NULL, \n\tcreated_at TIMESTAMP WITHOUT TIME ZONE NOT NULL, \n\tPRIMARY KEY (id)\n)',
        (
            'CREATE INDEX ix_emby_user_backups_server_id ON emby_user_backups (server_id)',
            'CREATE INDEX ix_emby_user_backups_user_id ON emby_user_backups (user_id)',
        ),
    ),
    (
        'emby_user_links',
        'CREATE TABLE emby_user_links (\n\tserver_id VARCHAR(36) NOT NULL, \n\tuser_id VARCHAR(36) NOT NULL, \n\tgroup_id VARCHAR(255), \n\tusername VARCHAR(255) NOT NULL, \n\tlink_key VARCHAR(255), \n\tis_leader BOOLEAN, \n\tupdated_at TIMESTAMP WITHOUT TIME ZONE, \n\tPRIMARY KEY (server_id, user_id)\n)',
        (
            'CREATE INDEX ix_emby_user_links_link_key ON emby_user_links (link_key)',
        ),
    ),
    (
        'jellyseerr_requests',
        'CREATE TABLE jellyseerr_requests (\n\trequest_id VARCHAR(50) NOT NULL, \n\ttmdb_id INTEGER, \n\tmedia_type VARCHAR(10), \n\tstatus VARCHAR(50), \n\tstatus_label VARCHAR(100), \n\trequested_by VARCHAR(255), \n\tcreated_at TIMESTAMP WITHOUT TIME ZONE, \n\tupdated_at TIMESTAMP WITHOUT TIME ZONE, \n\tpayload JSON NOT NULL, \n\tPRIMARY KEY (request_id)\n)',
        (
            'CREATE INDEX ix_jellyseerr_requests_media_type ON jellyseerr_requests (media_type)',
            'CREATE INDEX ix_jellyseerr_requests_tmdb_id ON jellyseerr_requests (tmdb_id)',
            'CREATE INDEX ix_jellyseerr_requests_updated_at ON jellyseerr_requests (updated_at)',
        ),
    ),
    (
        'justwatch_cache',
        'CREATE TABLE justwatch_cache (\n\tshow_name VARCHAR(500) NOT NULL, \n\tseason INTEGER NOT NULL, \n\tepisode INTEGER NOT NULL, \n\tis_available BOOLEAN, \n\tproviders JSON, \n\tlast_checked TIMESTAMP WITHOUT TIME ZONE NOT NULL, \n\tPRIMARY KEY (show_name, season, episode)\n)',
        (
            'CREATE INDEX ix_justwatch_cache_last_checked ON justwatch_cache (last_checked)',
        ),
    ),
    (
        'key_value',
        'CREATE TABLE key_value (\n\tkey VARCHAR(100) NOT NULL, \n\tvalue JSON NOT NULL, \n\tupdated_at TIMESTAMP WITHOUT TIME ZONE, \n\tPRIMARY KEY (key)\n)',
        (
        ),
    ),
    (
        'library_associations',
        'CREATE TABLE library_associations (\n\tserver_id VARCHAR(36) NOT NULL, \n\tlibrary_id VARCHAR(36) NOT NULL, \n\tlibrary_name VARCHAR(500), \n\tgroup_name VARCHAR(500), \n\tcollection_type VARCHAR(50), \n\tupdated_at TIMESTAMP WITHOUT TIME ZONE, \n\tPRIMARY KEY (server_id, library_id)\n)',
        (
            'CREATE INDEX ix_library_associations_group_name ON library_associations (group_name)',
        ),
    ),
    (
        'library_group_order',
        'CREATE TABLE library_group_order (\n\tcollection_type VARCHAR(50) NOT NULL, \n\tgroup_name VARCHAR(500) NOT NULL, \n\tposition INTEGER NOT NULL, \n\tupdated_at TIMESTAMP WITHOUT TIME ZONE, \n\tPRIMARY KEY (collection_type, group_name)\n)',
        (
        ),
    ),
    (
        'manual_search_history',
        'CREATE TABLE manual_search_history (\n\tid SERIAL NOT NULL, \n\tgenerated_at TIMESTAMP WITHOUT TIME ZONE NOT NULL, \n\tpayload JSON NOT NULL, \n\tPRIMARY KEY (id)\n)',
        (
            'CREATE INDEX ix_manual_search_history_generated_at ON manual_search_history (generated_at)',
        ),
    ),
    (
        'request_cache',
        'CREATE TABLE request_cache (\n\tid SERIAL NOT NULL, \n\trequest_id VARCHAR(50), \n\tpayload JSON NOT NULL, \n\tupdated_at TIMESTAMP WITHOUT TIME ZONE, \n\tPRIMARY KEY (id)\n)',
        (
            'CREATE INDEX ix_request_cache_request_id ON request_cache (request_id)',
        ),
    ),
    (
        'request_rule_entries',
        'CREATE TABLE request_rule_entries (\n\trequest_id VARCHAR(50) NOT NULL, \n\trules JSON NOT NULL, \n\tupdated_at TIMESTAMP WITHOUT TIME ZONE, \n\tPRIMARY KEY (request_id)\n)',
        (
        ),
    ),
    (
        'scan_results',
        'CREATE TABLE scan_results (\n\tid SERIAL NOT NULL, \n\tgenerated_at TIMESTAMP WITHOUT TIME ZONE NOT NULL, \n\tpayload JSON NOT NULL, \n\tPRIMARY KEY (id)\n)',
        (
            'CREATE INDEX ix_scan_results_generated_at ON scan_results (generated_at)',
        ),
    ),
    (
        'tab_order',
        'CREATE TABLE tab_order (\n\tpage VARCHAR(50) NOT NULL, \n\ttab_key VARCHAR(100) NOT NULL, \n\tposition INTEGER NOT NULL, \n\tupdated_at TIMESTAMP WITHOUT TIME ZONE, \n\tPRIMARY KEY (page, tab_key)\n)',
        (
        ),
    ),
    (
        'workflow_executions',
        'CREATE TABLE workflow_executions (\n\tid VARCHAR(36) NOT NULL, \n\tworkflow_type VARCHAR(20) NOT NULL, \n\tstatus VARCHAR(20) NOT NULL, \n\tcontext JSON, \n\terror TEXT, \n\tstarted_at TIMESTAMP WITHOUT TIME ZONE NOT NULL, \n\tcompleted_at TIMESTAMP WITHOUT TIME ZONE, \n\tPRIMARY KEY (id)\n)',
        (
            'CREATE INDEX ix_workflow_executions_started_at ON workflow_executions (started_at)',
            'CREATE INDEX ix_workflow_executions_status ON workflow_executions (status)',
        ),
    ),
    (
        'workflow_steps',
        'CREATE TABLE workflow_steps (\n\tid SERIAL NOT NULL, \n\tworkflow_id VARCHAR(36) NOT NULL, \n\tstep_id VARCHAR(20) NOT NULL, \n\tstep_index INTEGER NOT NULL, \n\tstatus VARCHAR(20) NOT NULL, \n\tprogress INTEGER, \n\tdetails TEXT, \n\tstarted_at TIMESTAMP WITHOUT TIME ZONE, \n\tcompleted_at TIMESTAMP WITHOUT TIME ZONE, \n\tduration_seconds INTEGER, \n\tPRIMARY KEY (id)\n)',
        (
            'CREATE INDEX ix_workflow_steps_workflow_id ON workflow_steps (workflow_id)',
        ),
    ),
)


_POSTGRES_AUTH_TABLES = (
    (
        'api_tokens',
        'CREATE TABLE api_tokens (\n\tid SERIAL NOT NULL, \n\tuser_id INTEGER NOT NULL, \n\tname VARCHAR(120) NOT NULL, \n\ttoken_hash VARCHAR(64) NOT NULL, \n\ttoken_prefix VARCHAR(16) NOT NULL, \n\tscopes TEXT NOT NULL, \n\tis_active BOOLEAN NOT NULL, \n\tcreated_at TIMESTAMP WITHOUT TIME ZONE NOT NULL, \n\tlast_used_at TIMESTAMP WITHOUT TIME ZONE, \n\trevoked_at TIMESTAMP WITHOUT TIME ZONE, \n\texpires_at TIMESTAMP WITHOUT TIME ZONE, \n\tPRIMARY KEY (id)\n)',
        (
            'CREATE UNIQUE INDEX ix_api_tokens_token_hash ON api_tokens (token_hash)',
            'CREATE INDEX ix_api_tokens_user_id ON api_tokens (user_id)',
        ),
    ),
    (
        'audit_logs',
        'CREATE TABLE audit_logs (\n\tid SERIAL NOT NULL, \n\tuser_id INTEGER, \n\tusername VARCHAR(80), \n\taction VARCHAR(120) NOT NULL, \n\tdetail TEXT, \n\tip_address VARCHAR(64), \n\tpath VARCHAR(255), \n\tmethod VARCHAR(10), \n\tuser_agent VARCHAR(255), \n\tcreated_at TIMESTAMP WITHOUT TIME ZONE NOT NULL, \n\tPRIMARY KEY (id)\n)',
        (
        ),
    ),
    (
        'legacy_auth_imports',
        'CREATE TABLE legacy_auth_imports (\n\tsource_fingerprint VARCHAR(64) NOT NULL, \n\tsource_path TEXT NOT NULL, \n\timported_at TIMESTAMP WITHOUT TIME ZONE NOT NULL, \n\tPRIMARY KEY (source_fingerprint)\n)',
        (
        ),
    ),
    (
        'user_interface_preferences',
        'CREATE TABLE user_interface_preferences (\n\tid SERIAL NOT NULL, \n\tuser_id INTEGER NOT NULL, \n\tprimary_navigation VARCHAR(20) NOT NULL, \n\tsecondary_navigation VARCHAR(20) NOT NULL, \n\tnavigation_order TEXT NOT NULL, \n\tupdated_at TIMESTAMP WITHOUT TIME ZONE NOT NULL, \n\tPRIMARY KEY (id)\n)',
        (
            'CREATE UNIQUE INDEX ix_user_interface_preferences_user_id ON user_interface_preferences (user_id)',
        ),
    ),
    (
        'users',
        'CREATE TABLE users (\n\tid SERIAL NOT NULL, \n\tusername VARCHAR(80) NOT NULL, \n\tpassword_hash VARCHAR(255) NOT NULL, \n\temail VARCHAR(120), \n\tis_active BOOLEAN NOT NULL, \n\tis_admin BOOLEAN NOT NULL, \n\trole VARCHAR(20) NOT NULL, \n\tcreated_at TIMESTAMP WITHOUT TIME ZONE NOT NULL, \n\tlast_login TIMESTAMP WITHOUT TIME ZONE, \n\tPRIMARY KEY (id), \n\tUNIQUE (email)\n)',
        (
            'CREATE UNIQUE INDEX ix_users_username ON users (username)',
        ),
    ),
)


_SQLITE_AUTH_TABLES = (
    (
        'api_tokens',
        'CREATE TABLE api_tokens (\n\tid INTEGER NOT NULL, \n\tuser_id INTEGER NOT NULL, \n\tname VARCHAR(120) NOT NULL, \n\ttoken_hash VARCHAR(64) NOT NULL, \n\ttoken_prefix VARCHAR(16) NOT NULL, \n\tscopes TEXT NOT NULL, \n\tis_active BOOLEAN NOT NULL, \n\tcreated_at DATETIME NOT NULL, \n\tlast_used_at DATETIME, \n\trevoked_at DATETIME, \n\texpires_at DATETIME, \n\tPRIMARY KEY (id)\n)',
        (
            'CREATE UNIQUE INDEX ix_api_tokens_token_hash ON api_tokens (token_hash)',
            'CREATE INDEX ix_api_tokens_user_id ON api_tokens (user_id)',
        ),
    ),
    (
        'audit_logs',
        'CREATE TABLE audit_logs (\n\tid INTEGER NOT NULL, \n\tuser_id INTEGER, \n\tusername VARCHAR(80), \n\taction VARCHAR(120) NOT NULL, \n\tdetail TEXT, \n\tip_address VARCHAR(64), \n\tpath VARCHAR(255), \n\tmethod VARCHAR(10), \n\tuser_agent VARCHAR(255), \n\tcreated_at DATETIME NOT NULL, \n\tPRIMARY KEY (id)\n)',
        (
        ),
    ),
    (
        'legacy_auth_imports',
        'CREATE TABLE legacy_auth_imports (\n\tsource_fingerprint VARCHAR(64) NOT NULL, \n\tsource_path TEXT NOT NULL, \n\timported_at DATETIME NOT NULL, \n\tPRIMARY KEY (source_fingerprint)\n)',
        (
        ),
    ),
    (
        'user_interface_preferences',
        'CREATE TABLE user_interface_preferences (\n\tid INTEGER NOT NULL, \n\tuser_id INTEGER NOT NULL, \n\tprimary_navigation VARCHAR(20) NOT NULL, \n\tsecondary_navigation VARCHAR(20) NOT NULL, \n\tnavigation_order TEXT NOT NULL, \n\tupdated_at DATETIME NOT NULL, \n\tPRIMARY KEY (id)\n)',
        (
            'CREATE UNIQUE INDEX ix_user_interface_preferences_user_id ON user_interface_preferences (user_id)',
        ),
    ),
    (
        'users',
        'CREATE TABLE users (\n\tid INTEGER NOT NULL, \n\tusername VARCHAR(80) NOT NULL, \n\tpassword_hash VARCHAR(255) NOT NULL, \n\temail VARCHAR(120), \n\tis_active BOOLEAN NOT NULL, \n\tis_admin BOOLEAN NOT NULL, \n\trole VARCHAR(20) NOT NULL, \n\tcreated_at DATETIME NOT NULL, \n\tlast_login DATETIME, \n\tPRIMARY KEY (id), \n\tUNIQUE (email)\n)',
        (
            'CREATE UNIQUE INDEX ix_users_username ON users (username)',
        ),
    ),
)


def _create_missing_tables(bind: Any, definitions: tuple[Any, ...]) -> None:
    """Create only tables absent before the immutable baseline runs."""
    from sqlalchemy import inspect

    existing = set(inspect(bind).get_table_names())
    for table_name, table_ddl, index_ddls in definitions:
        if table_name in existing:
            continue
        bind.exec_driver_sql(table_ddl)
        for index_ddl in index_ddls:
            bind.exec_driver_sql(index_ddl)
        existing.add(table_name)


def create_unified_baseline(bind: Any) -> None:
    """Create the schema exactly as revision 20260829_01 defined it."""
    if bind.dialect.name != "sqlite":
        _create_missing_tables(bind, _POSTGRES_STORAGE_TABLES)
    auth_tables = (
        _SQLITE_AUTH_TABLES
        if bind.dialect.name == "sqlite"
        else _POSTGRES_AUTH_TABLES
    )
    _create_missing_tables(bind, auth_tables)


REVISION_04_TABLE_COLUMNS = {
    'api_tokens': ('id', 'user_id', 'name', 'token_hash', 'token_prefix', 'scopes', 'is_active', 'created_at', 'last_used_at', 'revoked_at', 'expires_at'),
    'app_settings': ('id', 'data', 'updated_at'),
    'audit_logs': ('id', 'user_id', 'username', 'action', 'detail', 'ip_address', 'path', 'method', 'user_agent', 'created_at'),
    'emby_collection_backdrops': ('collection_id', 'mime_type', 'data', 'updated_at'),
    'emby_collection_definitions': ('id', 'data', 'updated_at'),
    'emby_collection_posters': ('collection_id', 'mime_type', 'data', 'updated_at'),
    'emby_group_passwords': ('group_id', 'password_enc', 'updated_at'),
    'emby_icon_bindings': ('target_type', 'target_id', 'profile_id', 'updated_at'),
    'emby_icon_profiles': ('id', 'label', 'is_group_profile', 'updated_at'),
    'emby_icon_rules': ('profile_id', 'column_key', 'icon_path', 'image_data', 'mime_type', 'updated_at'),
    'emby_image_cache': ('cache_key', 'image_url', 'mime_type', 'image_data', 'image_hash', 'created_at', 'expires_at'),
    'emby_latest_cache_changes': ('id', 'cache_kind', 'cache_item_id', 'sort_index', 'kind', 'label', 'season_number', 'episode_number', 'episode_title', 'quality', 'resolution', 'video_codec', 'audio_codec', 'audio_channels', 'container', 'bitrate', 'source_name', 'path', 'size', 'media_source_id', 'added_at', 'video_details', 'audio_details', 'audio_ita', 'audio_eng', 'audio_fra', 'audio_spa', 'audio_ger', 'audio_jpn', 'audio_langs', 'subtitle_langs', 'created_at'),
    'emby_latest_cache_errors': ('id', 'cache_kind', 'server_id', 'message', 'created_at'),
    'emby_latest_cache_items': ('id', 'cache_kind', 'item_type', 'server_id', 'item_id', 'signature', 'batch_id', 'title', 'original_title', 'series_name', 'season_name', 'season_number', 'episode_number', 'episode_title', 'year', 'overview', 'genres', 'community_rating', 'official_rating', 'runtime_minutes', 'added_at', 'premiere_date', 'child_count', 'season_count', 'episode_count', 'image_tag', 'image_url', 'poster_url', 'backdrop_url', 'banner_url', 'thumb_url', 'logo_url', 'emby_url', 'tagline', 'studios', 'cast_members', 'directors', 'creators', 'tmdb_id', 'imdb_id', 'tvdb_id', 'trakt_id', 'library_id', 'library_name', 'server_name', 'server_icon', 'server_icon_color', 'server_icon_style', 'update_type', 'update_label', 'tmdb_poster_url', 'tmdb_backdrop_url', 'tmdb_banner_url', 'tmdb_thumb_url', 'tmdb_rating', 'tmdb_votes', 'imdb_rating', 'imdb_votes', 'metacritic_rating', 'trakt_rating', 'trakt_votes', 'omdb_fetched_at', 'trakt_fetched_at', 'sort_ts'),
    'emby_latest_cache_meta': ('cache_kind', 'updated_at', 'limit', 'per_server_limit'),
    'emby_latest_progress': ('id', 'state', 'total', 'completed', 'message', 'started_at', 'updated_at'),
    'emby_latest_state_episodes': ('server_id', 'series_id', 'episode_key', 'episode_id', 'season_number', 'episode_number', 'title', 'last_seen_at', 'media_source_keys'),
    'emby_latest_state_movies': ('server_id', 'state_key', 'item_id', 'signature', 'title', 'year', 'last_seen_at', 'media_source_keys', 'notified', 'notified_at'),
    'emby_latest_state_series': ('server_id', 'series_id', 'title', 'year', 'last_seen_at', 'seasons', 'notified', 'notified_at'),
    'emby_latest_state_series_changes': ('id', 'group_id', 'sort_index', 'kind', 'label', 'season_number', 'episode_number', 'episode_title', 'quality', 'resolution', 'video_codec', 'audio_codec', 'audio_channels', 'container', 'bitrate', 'source_name', 'path', 'size', 'media_source_id', 'added_at', 'video_details', 'audio_details', 'audio_ita', 'audio_eng', 'audio_fra', 'audio_spa', 'audio_ger', 'audio_jpn', 'audio_langs', 'subtitle_langs'),
    'emby_latest_state_series_groups': ('id', 'server_id', 'series_id', 'sort_index', 'update_type', 'update_label', 'batch_id', 'added_at'),
    'emby_probe_blacklist': ('id', 'item_id', 'item_name', 'item_type', 'reason', 'error_type', 'retry_count', 'server_id', 'server_name', 'library_id', 'library_name', 'media_source_id', 'scope', 'failed_at'),
    'emby_probe_history': ('id', 'item_id', 'server_id', 'media_source_id', 'scope', 'name', 'library_name', 'processed_at', 'status', 'error_details', 'duration_ms'),
    'emby_probe_queue': ('id', 'item_id', 'server_id', 'media_source_id', 'scope', 'library_id', 'library_name', 'name', 'series_name', 'season_number', 'episode_number', 'year', 'media_type', 'path', 'added_at'),
    'emby_probe_recent_scans': ('id', 'server_id', 'library_id', 'server_name', 'event_type', 'status', 'last_scan_at', 'oldest_scanned_timestamp', 'payload'),
    'emby_user_backups': ('id', 'server_id', 'user_id', 'username', 'backup_type', 'data', 'created_at'),
    'emby_user_links': ('server_id', 'user_id', 'group_id', 'username', 'link_key', 'is_leader', 'updated_at'),
    'jellyseerr_requests': ('request_id', 'tmdb_id', 'media_type', 'status', 'status_label', 'requested_by', 'created_at', 'updated_at', 'payload'),
    'justwatch_cache': ('show_name', 'season', 'episode', 'is_available', 'providers', 'last_checked'),
    'key_value': ('key', 'value', 'updated_at'),
    'legacy_auth_imports': ('source_fingerprint', 'source_path', 'imported_at'),
    'library_associations': ('server_id', 'library_id', 'library_name', 'group_name', 'collection_type', 'updated_at'),
    'library_group_order': ('collection_type', 'group_name', 'position', 'updated_at'),
    'manual_search_history': ('id', 'generated_at', 'payload'),
    'request_cache': ('id', 'request_id', 'payload', 'updated_at'),
    'request_rule_entries': ('request_id', 'rules', 'updated_at'),
    'scan_results': ('id', 'generated_at', 'payload'),
    'tab_order': ('page', 'tab_key', 'position', 'updated_at'),
    'user_interface_preferences': ('id', 'user_id', 'primary_navigation', 'secondary_navigation', 'navigation_order', 'updated_at'),
    'users': ('id', 'username', 'password_hash', 'email', 'is_active', 'is_admin', 'role', 'created_at', 'last_login'),
    'workflow_executions': ('id', 'workflow_type', 'status', 'context', 'error', 'started_at', 'completed_at'),
    'workflow_steps': ('id', 'workflow_id', 'step_id', 'step_index', 'status', 'progress', 'details', 'started_at', 'completed_at', 'duration_seconds'),
}

REVISION_04_INDEX_NAMES = {
    'api_tokens': ('ix_api_tokens_token_hash', 'ix_api_tokens_user_id'),
    'app_settings': (),
    'audit_logs': (),
    'emby_collection_backdrops': (),
    'emby_collection_definitions': (),
    'emby_collection_posters': (),
    'emby_group_passwords': (),
    'emby_icon_bindings': ('ix_emby_icon_bindings_profile_id',),
    'emby_icon_profiles': (),
    'emby_icon_rules': (),
    'emby_image_cache': (),
    'emby_latest_cache_changes': ('ix_emby_latest_cache_changes_cache_item_id', 'ix_emby_latest_cache_changes_cache_kind'),
    'emby_latest_cache_errors': ('ix_emby_latest_cache_errors_cache_kind', 'ix_emby_latest_cache_errors_server_id'),
    'emby_latest_cache_items': ('ix_emby_latest_cache_items_batch_id', 'ix_emby_latest_cache_items_cache_kind', 'ix_emby_latest_cache_items_item_id', 'ix_emby_latest_cache_items_item_type', 'ix_emby_latest_cache_items_server_id', 'ix_emby_latest_cache_items_signature', 'ix_emby_latest_cache_items_sort_ts', 'ix_latest_cache_kind_server_type', 'ix_latest_cache_kind_sort'),
    'emby_latest_cache_meta': (),
    'emby_latest_progress': (),
    'emby_latest_state_episodes': ('ix_emby_latest_state_episodes_episode_id', 'ix_emby_latest_state_episodes_last_seen_at'),
    'emby_latest_state_movies': ('ix_emby_latest_state_movies_item_id', 'ix_emby_latest_state_movies_last_seen_at'),
    'emby_latest_state_series': ('ix_emby_latest_state_series_last_seen_at',),
    'emby_latest_state_series_changes': ('ix_emby_latest_state_series_changes_group_id',),
    'emby_latest_state_series_groups': ('ix_emby_latest_state_series_groups_series_id', 'ix_emby_latest_state_series_groups_server_id'),
    'emby_probe_blacklist': ('ix_emby_probe_blacklist_item_id', 'ix_emby_probe_blacklist_server_id'),
    'emby_probe_history': ('ix_emby_probe_history_item_id', 'ix_emby_probe_history_server_id'),
    'emby_probe_queue': ('ix_emby_probe_queue_item_id', 'ix_emby_probe_queue_server_id'),
    'emby_probe_recent_scans': ('ix_emby_probe_recent_scans_library_id', 'ix_emby_probe_recent_scans_server_id'),
    'emby_user_backups': ('ix_emby_user_backups_server_id', 'ix_emby_user_backups_user_id'),
    'emby_user_links': ('ix_emby_user_links_link_key',),
    'jellyseerr_requests': ('ix_jellyseerr_requests_media_type', 'ix_jellyseerr_requests_tmdb_id', 'ix_jellyseerr_requests_updated_at'),
    'justwatch_cache': ('ix_justwatch_cache_last_checked',),
    'key_value': (),
    'legacy_auth_imports': (),
    'library_associations': ('ix_library_associations_group_name',),
    'library_group_order': (),
    'manual_search_history': ('ix_manual_search_history_generated_at',),
    'request_cache': ('ix_request_cache_request_id',),
    'request_rule_entries': (),
    'scan_results': ('ix_scan_results_generated_at',),
    'tab_order': (),
    'user_interface_preferences': ('ix_user_interface_preferences_user_id',),
    'users': ('ix_users_username',),
    'workflow_executions': ('ix_workflow_executions_started_at', 'ix_workflow_executions_status'),
    'workflow_steps': ('ix_workflow_steps_workflow_id',),
}

REVISION_04_UNIQUE_COLUMN_SETS = {
    'api_tokens': (),
    'app_settings': (),
    'audit_logs': (),
    'emby_collection_backdrops': (),
    'emby_collection_definitions': (),
    'emby_collection_posters': (),
    'emby_group_passwords': (),
    'emby_icon_bindings': (),
    'emby_icon_profiles': (),
    'emby_icon_rules': (),
    'emby_image_cache': (),
    'emby_latest_cache_changes': (),
    'emby_latest_cache_errors': (),
    'emby_latest_cache_items': (),
    'emby_latest_cache_meta': (),
    'emby_latest_progress': (),
    'emby_latest_state_episodes': (),
    'emby_latest_state_movies': (),
    'emby_latest_state_series': (),
    'emby_latest_state_series_changes': (),
    'emby_latest_state_series_groups': (),
    'emby_probe_blacklist': (),
    'emby_probe_history': (),
    'emby_probe_queue': (),
    'emby_probe_recent_scans': (),
    'emby_user_backups': (),
    'emby_user_links': (),
    'jellyseerr_requests': (),
    'justwatch_cache': (),
    'key_value': (),
    'legacy_auth_imports': (),
    'library_associations': (),
    'library_group_order': (),
    'manual_search_history': (),
    'request_cache': (),
    'request_rule_entries': (),
    'scan_results': (),
    'tab_order': (),
    'user_interface_preferences': (),
    'users': (('email',),),
    'workflow_executions': (),
    'workflow_steps': (),
}


def _revision_column_type(type_sql: str) -> Any:
    """Translate the frozen PostgreSQL DDL subset into SQLAlchemy types."""
    if type_sql.endswith("[]"):
        return ARRAY(_revision_column_type(type_sql[:-2]))
    if type_sql == "SERIAL" or type_sql == "INTEGER":
        return Integer()
    if type_sql == "BIGINT":
        return BigInteger()
    if type_sql == "BOOLEAN":
        return Boolean()
    if type_sql == "TEXT":
        return Text()
    if type_sql == "JSON":
        return JSON()
    if type_sql == "BYTEA":
        return LargeBinary()
    if type_sql == "TIMESTAMP WITHOUT TIME ZONE":
        return DateTime()
    if type_sql == "VARCHAR":
        return String()
    varchar = re.fullmatch(r"VARCHAR\((\d+)\)", type_sql)
    if varchar:
        return String(int(varchar.group(1)))
    raise RuntimeError(f"Unsupported frozen revision-04 type: {type_sql}")


def _frozen_table_parts(table_ddl: str) -> tuple[list[tuple[str, str, bool]], tuple[str, ...]]:
    columns: list[tuple[str, str, bool]] = []
    primary_key: tuple[str, ...] = ()
    for raw_line in table_ddl.splitlines()[1:-1]:
        line = raw_line.strip().rstrip(",")
        primary_match = re.fullmatch(r"PRIMARY KEY \(([^)]+)\)", line)
        if primary_match:
            primary_key = tuple(
                part.strip().strip('"') for part in primary_match.group(1).split(",")
            )
            continue
        if line.startswith("UNIQUE ("):
            continue
        column_match = re.fullmatch(r'"?([a-zA-Z_][a-zA-Z0-9_]*)"? (.+)', line)
        if not column_match:
            continue
        column_name, declaration = column_match.groups()
        nullable = not declaration.endswith(" NOT NULL")
        type_sql = declaration.removesuffix(" NOT NULL")
        columns.append((column_name, type_sql, nullable))
    return columns, primary_key


def _frozen_index_parts(index_ddl: str) -> tuple[str, tuple[str, ...], bool]:
    match = re.fullmatch(
        r"CREATE (UNIQUE )?INDEX ([a-zA-Z_][a-zA-Z0-9_]*) "
        r"ON [a-zA-Z_][a-zA-Z0-9_]* \(([^)]+)\)",
        index_ddl,
    )
    if not match:
        raise RuntimeError(f"Unsupported frozen revision-04 index: {index_ddl}")
    return (
        match.group(2),
        tuple(part.strip().strip('"') for part in match.group(3).split(",")),
        bool(match.group(1)),
    )


def _build_revision_04_metadata() -> MetaData:
    """Build historical metadata exclusively from the immutable baseline DDL."""
    metadata = MetaData()
    definitions = (*_POSTGRES_STORAGE_TABLES, *_POSTGRES_AUTH_TABLES)
    for table_name, table_ddl, index_ddls in definitions:
        allowed_columns = set(REVISION_04_TABLE_COLUMNS.get(table_name, ()))
        if not allowed_columns:
            continue
        column_parts, primary_key = _frozen_table_parts(table_ddl)
        table = Table(
            table_name,
            metadata,
            *(
                Column(
                    column_name,
                    _revision_column_type(type_sql),
                    primary_key=column_name in primary_key,
                    nullable=nullable,
                )
                for column_name, type_sql, nullable in column_parts
                if column_name in allowed_columns
            ),
        )
        for unique_columns in REVISION_04_UNIQUE_COLUMN_SETS.get(table_name, ()):
            UniqueConstraint(*(table.c[name] for name in unique_columns))
        allowed_indexes = set(REVISION_04_INDEX_NAMES.get(table_name, ()))
        for index_ddl in index_ddls:
            index_name, index_columns, unique = _frozen_index_parts(index_ddl)
            if index_name not in allowed_indexes:
                continue
            Index(index_name, *(table.c[name] for name in index_columns), unique=unique)
    return metadata


REVISION_04_METADATA = _build_revision_04_metadata()


__all__ = [
    "REVISION_04_INDEX_NAMES",
    "REVISION_04_METADATA",
    "REVISION_04_TABLE_COLUMNS",
    "REVISION_04_UNIQUE_COLUMN_SETS",
    "create_unified_baseline",
]
