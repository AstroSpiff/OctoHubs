def test_event_bridge_merge_preserves_hidden_server_settings():
    from emby_runtime.event_bridge_settings import normalize_event_bridge_config
    from web.config_routes import _merged_event_bridge_config

    current = normalize_event_bridge_config(
        {
            "SERVERS": {
                "green": {"ENABLED": False, "RETRY_COUNT": 7},
                "purple": {"ENABLED": True, "RETRY_COUNT": 1},
            }
        }
    )
    submitted = {
        "purple": current["SERVERS"]["purple"] | {"RETRY_COUNT": 3},
    }

    merged = _merged_event_bridge_config(current, submitted)

    assert merged["SERVERS"]["green"]["ENABLED"] is False
    assert merged["SERVERS"]["green"]["RETRY_COUNT"] == 7
    assert merged["SERVERS"]["purple"]["RETRY_COUNT"] == 3


def test_event_bridge_server_settings_are_hidden_until_plugin_seen():
    from emby_runtime.event_bridge_settings import normalize_event_bridge_config
    from web.config_routes import _event_bridge_servers_for_view

    servers = [
        {"id": "green", "alias": "Green"},
        {"id": "purple", "alias": "Purple"},
        {"id": "blue", "alias": "Blue"},
    ]
    status = {
        "servers": [
            {"server_id": "purple", "connected": False, "received_count": 1},
            {"server_id": "blue", "connected": True, "received_count": 0},
        ]
    }

    items = _event_bridge_servers_for_view(servers, normalize_event_bridge_config({}), status)
    by_id = {item["id"]: item for item in items}

    assert by_id["green"]["settings_editable"] is False
    assert by_id["purple"]["settings_editable"] is True
    assert by_id["blue"]["settings_editable"] is True
