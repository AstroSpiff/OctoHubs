import json
from pathlib import Path

from sqlalchemy import create_engine, inspect, text


def test_interface_preferences_are_scoped_to_each_auth_account(tmp_path, monkeypatch):
    import core.auth as auth

    previous_session = auth.db_session
    database_url = f"sqlite:///{Path(tmp_path) / 'auth-preferences.db'}"
    try:
        auth.init_auth(database_url=database_url, allow_sqlite_for_tests=True)
        first = auth.create_user("first-user", "password-one")
        second = auth.create_user("second-user", "password-two")
        assert first is not None and second is not None

        assert auth.get_user_interface_preferences(first.id) == {
            "primary_navigation": "top",
            "secondary_navigation": "tabs",
        }
        assert auth.save_user_interface_preferences(
            first.id,
            {"primary_navigation": "sidebar", "secondary_navigation": "sidebar"},
        ) == {"primary_navigation": "sidebar", "secondary_navigation": "sidebar"}
        assert auth.get_user_interface_preferences(first.id) == {
            "primary_navigation": "sidebar",
            "secondary_navigation": "sidebar",
        }
        assert auth.get_user_interface_preferences(second.id) == {
            "primary_navigation": "top",
            "secondary_navigation": "tabs",
        }
        assert auth.get_user_interface_order(first.id, "primary") is None
        assert auth.save_user_interface_order(
            first.id,
            "primary",
            ["probe", "operations", "probe", ""],
        ) == ["probe", "operations"]
        assert auth.get_user_interface_order(first.id, "primary") == ["probe", "operations"]
        assert auth.get_user_interface_order(second.id, "primary") is None
        assert auth.save_user_interface_order(first.id, "dashboard", ["summary", "rules"]) == ["summary", "rules"]
        assert auth.get_user_interface_order(first.id, "research") is None
        assert auth.migrate_user_interface_navigation_orders({}, {"dashboard": "research"}) == 1
        assert auth.get_user_interface_order(first.id, "research") == ["summary", "rules"]
        preference = auth.db_session.query(auth.UserInterfacePreference).filter_by(user_id=first.id).one()
        saved_orders = json.loads(preference.navigation_order)
        assert saved_orders["research"] == ["summary", "rules"]
        assert "dashboard" not in saved_orders

    finally:
        if auth.db_session is not None:
            auth.db_session.remove()
        auth.db_session = previous_session


def test_interface_preferences_migrate_a_preexisting_auth_database(tmp_path):
    import core.auth as auth

    database_url = f"sqlite:///{Path(tmp_path) / 'auth-migration.db'}"
    engine = create_engine(database_url)
    with engine.begin() as connection:
        connection.execute(text("""
            CREATE TABLE user_interface_preferences (
                id INTEGER PRIMARY KEY,
                user_id INTEGER NOT NULL UNIQUE,
                primary_navigation VARCHAR(20) NOT NULL,
                secondary_navigation VARCHAR(20) NOT NULL,
                updated_at DATETIME NOT NULL
            )
        """))

    from core.database_migrations import upgrade_database

    upgrade_database(database_url)

    columns = {column["name"] for column in inspect(engine).get_columns("user_interface_preferences")}
    assert "navigation_order" in columns
