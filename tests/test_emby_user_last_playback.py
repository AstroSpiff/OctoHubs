from emby_users import api_client_items
from emby_users.user_ops_manager import UserOpsManager


def test_last_playback_request_includes_user_data(monkeypatch):
    calls = []

    def fake_call(server, path, params=None):
        calls.append((server, path, params))
        return True, {"Items": [{"Name": "Obsession", "UserData": {"LastPlayedDate": "2026-08-06T22:40:51Z"}}]}

    monkeypatch.setattr(api_client_items, "_call_emby_api", fake_call)

    item = api_client_items._fetch_emby_user_last_playback({"id": "green"}, "user-1")

    assert item["UserData"]["LastPlayedDate"] == "2026-08-06T22:40:51Z"
    assert calls[0][1] == "Users/user-1/Items"
    assert calls[0][2]["Fields"] == "UserData,SeriesName"


def test_extended_user_details_uses_last_played_date_from_emby_user_data():
    manager = UserOpsManager(
        get_server_by_id=lambda _server_id: {"id": "green"},
        fetch_user_details=lambda _server, _user_id: ({"LastActivityDate": "2026-08-06T22:40:51Z"}, None),
        fetch_users_list=lambda _server: ([], None),
        update_user_policy=lambda _server, _user_id, _policy: (True, None),
        rename_user=lambda _server, _user_id, _name: (True, None),
        fetch_user_last_playback=lambda _server, _user_id: {
            "Name": "Obsession",
            "UserData": {"LastPlayedDate": "2026-08-06T22:40:51Z"},
        },
    )

    details = manager.get_user_extended_details("green", "user-1")

    assert details["last_played_title"] == "Obsession"
    assert details["last_played_date"] == "2026-08-06T22:40:51Z"
