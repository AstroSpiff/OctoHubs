from typing import List, Tuple, Optional, Dict, Any, Callable

from core.storage.field_limits import build_unlinked_group_id


class GroupUserResolver:
    def __init__(self, storage):
        self.storage = storage
        self._get_users_dashboard_data: Optional[Callable[[], Dict[str, Any]]] = None

    def set_get_users_dashboard_data(self, getter: Callable[[], Dict[str, Any]]) -> None:
        self._get_users_dashboard_data = getter

    def get_unlinked_group_id(self, server_id: str, user_id: str) -> str:
        return build_unlinked_group_id(server_id, user_id)

    def get_group_users(self, group_id: str) -> List[Tuple[str, str, Optional[str]]]:
        if group_id == "owners":
            if not self._get_users_dashboard_data:
                return []
            data = self._get_users_dashboard_data()
            owners = next((g for g in data.get("groups", []) if g.get("id") == "owners"), None)
            if not owners:
                return []
            return [(u["server_id"], u["user_id"], u.get("name")) for u in owners.get("users", [])]

        if group_id.startswith("unlinked_"):
            rest = group_id[len("unlinked_"):]
            if "_" in rest:
                server_id, user_id = rest.split("_", 1)
                return [(server_id, user_id, None)]
            return []

        links = self.storage.get_user_links(group_id=group_id)
        return [(link["server_id"], link["user_id"], link.get("username")) for link in links]
