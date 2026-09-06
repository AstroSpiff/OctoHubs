"""Regression coverage for the thirteenth backend review."""

from core import auth
from emby_libraries import snapshots


def test_item_details_rejects_non_segment_identifier_without_outbound_call(monkeypatch):
    outbound_calls = []
    monkeypatch.setattr(
        snapshots,
        "_call_emby_api",
        lambda *args, **kwargs: outbound_calls.append((args, kwargs)),
    )

    payload, status_code = snapshots._build_item_details_snapshot(
        "server-1",
        "../Users/Query",
    )

    assert status_code == 400
    assert payload == {"success": False, "message": "ID elemento Emby non valido"}
    assert outbound_calls == []


def test_item_details_uses_validated_identifier_for_emby_path(monkeypatch):
    server = {"id": "server-1", "name": "Server", "enabled": True}
    outbound_paths = []

    def call_emby(_server, path, **_kwargs):
        outbound_paths.append(path)
        return True, {"Id": "item_1", "Name": "Film", "Type": "Movie"}

    monkeypatch.setattr(snapshots, "load_config", lambda: ({"EMBY": {}}, True))
    monkeypatch.setattr(snapshots, "_resolve_emby_server", lambda _config, _server_id: server)
    monkeypatch.setattr(snapshots, "_call_emby_api", call_emby)

    payload, status_code = snapshots._build_item_details_snapshot("server-1", "item_1")

    assert status_code == 200
    assert payload["success"] is True
    assert outbound_paths == ["Items/item_1"]


def test_has_users_checks_only_the_first_identifier(monkeypatch):
    class Query:
        first_calls = 0

        def first(self):
            self.first_calls += 1
            return (7,)

        def all(self):
            raise AssertionError("has_users must not materialize every account")

    query = Query()

    class SessionRegistry:
        def query(self, _column):
            return query

    monkeypatch.setattr(auth, "db_session", SessionRegistry())

    assert auth.has_users() is True
    assert query.first_calls == 1
