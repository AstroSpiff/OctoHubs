from core.storage import DatabaseStorage
from core.storage.storage_models import (
    EmbyGroupPassword,
    EmbyIconBinding,
    EmbyUserCreationJournal,
    EmbyUserLink,
    KeyValueEntry,
    create_engine,
    sessionmaker,
)


def test_deleted_user_cleanup_removes_user_and_dissolved_group_state_atomically(tmp_path):
    database_url = f"sqlite:///{tmp_path / 'deleted-user.db'}"
    engine = create_engine(database_url, future=True)
    for model in (
        EmbyUserLink,
        EmbyGroupPassword,
        EmbyIconBinding,
        EmbyUserCreationJournal,
        KeyValueEntry,
    ):
        model.__table__.create(engine, checkfirst=True)
    storage = DatabaseStorage({"URL": database_url})
    storage._engine = engine
    storage._Session = sessionmaker(bind=engine, expire_on_commit=False)
    storage.set_user_link("server-a", "user-a", "group-a", "A", is_leader=True)
    storage.set_user_link("server-b", "user-b", "group-a", "B", is_leader=False)
    storage.set_key_value("emby_user_settings:server-a:user-a", {"settings": {}})
    storage.set_key_value("emby_user_sync_state:playstate:server-a:user-a", {"items": []})
    storage.set_key_value("group_settings:group-a", {"auto_sync": True})
    storage.save_group_password("group-a", "group-secret")
    storage.save_group_password("unlinked_server-a_user-a", "user-secret")
    assert storage.reserve_emby_user_creation("server-a", " Alice ") is True
    storage.mark_emby_user_creation_remote("server-a", "ALICE")

    result = storage.cleanup_deleted_emby_user("server-a", "user-a", "alice")

    assert result == {"group_id": "group-a", "dissolved": True}
    assert storage.get_user_links(group_id="group-a") == []
    assert storage.get_key_value("emby_user_settings:server-a:user-a") is None
    assert storage.get_key_value("emby_user_sync_state:playstate:server-a:user-a") is None
    assert storage.get_key_value("group_settings:group-a") is None
    assert storage.get_group_password("group-a") is None
    assert storage.get_group_password("unlinked_server-a_user-a") is None
    assert storage.get_emby_user_creation("server-a", "Alice") is None
    assert storage.reserve_emby_user_creation("server-a", "Alice") is True
