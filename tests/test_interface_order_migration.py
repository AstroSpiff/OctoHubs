"""Tests for the one-time user-interface order migration."""

from __future__ import annotations

import json
from pathlib import Path


class _Storage:
    def __init__(self, orders):
        self.orders = orders
        self.values = {}

    def load_tab_order(self, page):
        return self.orders.get(page, {})

    def get_key_value(self, key):
        return self.values.get(key)

    def set_key_value(self, key, value):
        self.values[key] = value


def test_shared_navigation_order_is_migrated_once_into_profiles(tmp_path, monkeypatch):
    import core.auth as auth
    from services.interface_order_migration import MIGRATION_KEY, migrate_legacy_interface_orders

    previous_session = auth.db_session
    try:
        auth.init_auth(
            create_default_admin=False,
            database_url=f"sqlite:///{Path(tmp_path) / 'auth-navigation.db'}",
            allow_sqlite_for_tests=True,
        )
        first = auth.create_user("first-user", "password-one")
        second = auth.create_user("second-user", "password-two")
        assert first is not None and second is not None
        assert auth.save_user_interface_order(first.id, "research", ["requests", "rules"]) == ["requests", "rules"]
        assert auth.save_user_interface_order(second.id, "dashboard", ["summary", "rules"]) == ["summary", "rules"]

        storage = _Storage(
            {
                "primary": {"research": 1, "emby": 0},
                "emby": {"users": 1, "live": 0},
                "dashboard": {"summary": 0, "rules": 1},
            }
        )

        result = migrate_legacy_interface_orders(storage)

        assert result == {"completed": True, "already_completed": False, "profiles": 2}
        assert MIGRATION_KEY in storage.values
        assert auth.get_user_interface_order(first.id, "research") == ["requests", "rules"]
        assert auth.get_user_interface_order(second.id, "research") == ["summary", "rules"]
        assert auth.get_user_interface_order(first.id, "primary") == ["emby", "research"]
        assert auth.get_user_interface_order(second.id, "emby") == ["live", "users"]

        preference = auth.db_session.query(auth.UserInterfacePreference).filter_by(user_id=second.id).one()
        assert "dashboard" not in json.loads(preference.navigation_order)
        assert migrate_legacy_interface_orders(storage) == {
            "completed": True,
            "already_completed": True,
            "profiles": 0,
        }
    finally:
        if auth.db_session is not None:
            auth.db_session.remove()
        auth.db_session = previous_session
