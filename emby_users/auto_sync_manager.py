import logging
from typing import Dict, Any, List, Callable

from emby_users.sync_state_refresh import refresh_sync_states

logger = logging.getLogger(__name__)


class AutoSyncManager:
    def __init__(
        self,
        get_users_dashboard_data: Callable[[], Dict[str, Any]],
        sync_merge_playstate: Callable[[List[tuple], bool], Dict[str, Any]],
        sync_user_playstate: Callable[[str, str, List[tuple], bool], Dict[str, Any]],
        sync_user_playstate_exact: Callable[[str, str, List[tuple], bool], Dict[str, Any]],
        sync_user_playstate_to_state: Callable[[Dict[str, Dict[str, Any]], List[tuple], bool], Dict[str, Any]],
        sync_user_config: Callable[[str, str, List[tuple], Any], Dict[str, Any]],
        sync_library_access: Callable[[str, str, List[tuple]], Dict[str, Any]],
        sync_user_favorites: Callable[[str, str, List[tuple]], Dict[str, Any]],
        sync_user_favorites_exact: Callable[[str, str, List[tuple]], Dict[str, Any]],
        sync_user_favorites_to_keys: Callable[[List[str] | set, List[tuple]], Dict[str, Any]],
        sync_merge_favorites: Callable[[List[tuple]], Dict[str, Any]],
        sync_user_playlists: Callable[[str, str, List[tuple]], Dict[str, Any]],
        sync_user_playlists_exact: Callable[[str, str, List[tuple]], Dict[str, Any]],
        sync_user_playlists_to_payload: Callable[[Dict[str, Dict[str, Any]], List[tuple], Any], Dict[str, Any]],
        sync_merge_playlists: Callable[[List[tuple]], Dict[str, Any]],
        mark_group_bootstrap_done: Callable[[str, str], bool],
        mark_group_sync_result: Callable[[str, str, str, Dict[str, Any]], bool],
        state_tracker,
    ):
        self._get_users_dashboard_data = get_users_dashboard_data
        self._sync_merge_playstate = sync_merge_playstate
        self._sync_user_playstate = sync_user_playstate
        self._sync_user_playstate_exact = sync_user_playstate_exact
        self._sync_user_playstate_to_state = sync_user_playstate_to_state
        self._sync_user_config = sync_user_config
        self._sync_library_access = sync_library_access
        self._sync_user_favorites = sync_user_favorites
        self._sync_user_favorites_exact = sync_user_favorites_exact
        self._sync_user_favorites_to_keys = sync_user_favorites_to_keys
        self._sync_merge_favorites = sync_merge_favorites
        self._sync_user_playlists = sync_user_playlists
        self._sync_user_playlists_exact = sync_user_playlists_exact
        self._sync_user_playlists_to_payload = sync_user_playlists_to_payload
        self._sync_merge_playlists = sync_merge_playlists
        self._mark_group_bootstrap_done = mark_group_bootstrap_done
        self._mark_group_sync_result = mark_group_sync_result
        self._state_tracker = state_tracker

    def _latest_source(self, domain: str, participants: List[tuple], progress_callback=None):
        state = self._state_tracker.choose_latest(domain, participants, progress_callback=progress_callback)
        if not state:
            return None, []
        source_pair = (state.get("server_id"), state.get("user_id"))
        target_pairs = [pair for pair in participants if pair != source_pair]
        return state, target_pairs

    def _run_latest_wins(
        self,
        domain: str,
        participants: List[tuple],
        sync_func: Callable,
        *args,
        progress_callback=None,
    ) -> Dict[str, Any]:
        logger.warning("[USER_SYNC] Latest-wins start domain=%s participants=%s", domain, len(participants))
        state, targets = self._latest_source(domain, participants, progress_callback=progress_callback)
        if not state or not targets:
            return {"skipped": True, "reason": "latest source unavailable"}
        logger.warning(
            "[USER_SYNC] Latest-wins apply domain=%s source=%s/%s targets=%s",
            domain,
            state["server_id"],
            state["user_id"],
            len(targets),
        )
        result = sync_func(state["server_id"], state["user_id"], targets, *args)
        result["latest_source"] = {
            "server_id": state["server_id"],
            "user_id": state["user_id"],
            "updated_at": state.get("updated_at")
        }
        logger.warning("[USER_SYNC] Latest-wins done domain=%s result=%s", domain, result)
        return result

    def _run_favorites_delta_sync(
        self,
        participants: List[tuple],
        progress_callback=None,
    ) -> Dict[str, Any]:
        logger.warning("[USER_SYNC] Delta sync start domain=favorites participants=%s", len(participants))
        states = [
            state
            for state in self._state_tracker.refresh_many_with_diff(
                "favorites",
                participants,
                progress_callback=progress_callback,
            )
            if not state.get("error")
        ]
        if not states:
            return {"skipped": True, "reason": "favorites snapshots unavailable"}

        baseline_keys = set()
        added_keys = set()
        removed_keys = set()
        initial_keys = set()
        changed_states = []

        for state in states:
            snapshot = state.get("snapshot") or {}
            previous_snapshot = state.get("previous_snapshot") or {}
            current = set(snapshot.get("favorites") or [])
            previous = set(previous_snapshot.get("favorites") or [])
            diff = state.get("diff") or {}

            if previous:
                baseline_keys.update(previous)
            if diff.get("initial"):
                initial_keys.update(current)
            else:
                added_keys.update(diff.get("added") or [])
                removed_keys.update(diff.get("removed") or [])
            if state.get("changed"):
                changed_states.append(state)

        desired_keys = (baseline_keys | initial_keys | added_keys) - removed_keys
        conflicts = added_keys & removed_keys
        if conflicts and changed_states:
            latest_state = max(changed_states, key=lambda state: state.get("updated_at") or "")
            latest_keys = set((latest_state.get("snapshot") or {}).get("favorites") or [])
            for key in conflicts:
                if key in latest_keys:
                    desired_keys.add(key)
                else:
                    desired_keys.discard(key)

        logger.warning(
            "[USER_SYNC] Delta sync apply domain=favorites baseline=%s added=%s removed=%s conflicts=%s desired=%s",
            len(baseline_keys),
            len(added_keys | initial_keys),
            len(removed_keys),
            len(conflicts),
            len(desired_keys),
        )
        result = self._sync_user_favorites_to_keys(desired_keys, participants)
        result["delta"] = {
            "baseline": len(baseline_keys),
            "added": len(added_keys | initial_keys),
            "removed": len(removed_keys),
            "conflicts": len(conflicts),
            "desired": len(desired_keys),
        }
        logger.warning("[USER_SYNC] Delta sync done domain=favorites result=%s", result)
        return result

    def _run_playstate_delta_sync(
        self,
        participants: List[tuple],
        include_resume: bool,
        progress_callback=None,
    ) -> Dict[str, Any]:
        logger.warning("[USER_SYNC] Delta sync start domain=playstate participants=%s", len(participants))
        states = [
            state
            for state in self._state_tracker.refresh_many_with_diff(
                "playstate",
                participants,
                progress_callback=progress_callback,
            )
            if not state.get("error")
        ]
        if not states:
            return {"skipped": True, "reason": "playstate snapshots unavailable"}

        desired_state = {}
        latest_ops = {}
        initial_count = 0
        for state in states:
            snapshot = state.get("snapshot") or {}
            previous_snapshot = state.get("previous_snapshot") or {}
            current_items = snapshot.get("items") or {}
            previous_items = previous_snapshot.get("items") or {}
            diff = state.get("diff") or {}
            updated_at = state.get("updated_at") or ""

            desired_state.update(previous_items)
            if diff.get("initial"):
                initial_count += len(current_items)
                for key, value in current_items.items():
                    latest_ops[key] = (updated_at, "set", value)
                continue

            for key in diff.get("added") or []:
                if key in current_items and updated_at >= latest_ops.get(key, ("", "", None))[0]:
                    latest_ops[key] = (updated_at, "set", current_items[key])
            for key in diff.get("changed") or []:
                if key in current_items and updated_at >= latest_ops.get(key, ("", "", None))[0]:
                    latest_ops[key] = (updated_at, "set", current_items[key])
            for key in diff.get("removed") or []:
                if updated_at >= latest_ops.get(key, ("", "", None))[0]:
                    latest_ops[key] = (updated_at, "remove", None)

        set_count = 0
        remove_count = 0
        for key, (_updated_at, op, value) in latest_ops.items():
            if op == "remove":
                desired_state.pop(key, None)
                remove_count += 1
            else:
                desired_state[key] = value
                set_count += 1

        logger.warning(
            "[USER_SYNC] Delta sync apply domain=playstate baseline=%s set=%s removed=%s initial=%s desired=%s",
            len(desired_state) - set_count + remove_count,
            set_count,
            remove_count,
            initial_count,
            len(desired_state),
        )
        result = self._sync_user_playstate_to_state(desired_state, participants, include_resume)
        result["delta"] = {
            "set": set_count,
            "removed": remove_count,
            "initial": initial_count,
            "desired": len(desired_state),
        }
        logger.warning("[USER_SYNC] Delta sync done domain=playstate result=%s", result)
        return result

    def _run_playlists_delta_sync(
        self,
        participants: List[tuple],
        progress_callback=None,
    ) -> Dict[str, Any]:
        logger.warning("[USER_SYNC] Delta sync start domain=playlists participants=%s", len(participants))
        states = [
            state
            for state in self._state_tracker.refresh_many_with_diff(
                "playlists",
                participants,
                progress_callback=progress_callback,
            )
            if not state.get("error")
        ]
        if not states:
            return {"skipped": True, "reason": "playlist snapshots unavailable"}

        desired_playlists = {}
        playlist_ops = {}
        item_ops = {}
        latest_orders = {}

        for state in states:
            snapshot = state.get("snapshot") or {}
            previous_snapshot = state.get("previous_snapshot") or {}
            current_playlists = snapshot.get("playlists") or {}
            previous_playlists = previous_snapshot.get("playlists") or {}
            diff = state.get("diff") or {}
            updated_at = state.get("updated_at") or ""

            desired_playlists.update(previous_playlists)
            if diff.get("initial"):
                for name, playlist in current_playlists.items():
                    playlist_ops[name] = (updated_at, "set", playlist)
                continue

            for name in diff.get("added") or []:
                playlist = current_playlists.get(name)
                if playlist and updated_at >= playlist_ops.get(name, ("", "", None))[0]:
                    playlist_ops[name] = (updated_at, "set", playlist)
            for name in diff.get("removed") or []:
                if updated_at >= playlist_ops.get(name, ("", "", None))[0]:
                    playlist_ops[name] = (updated_at, "remove", None)

            changed = diff.get("changed") or {}
            for name, item_diff in changed.items():
                playlist = current_playlists.get(name) or {}
                items = playlist.get("items") or []
                for key in item_diff.get("added") or []:
                    if updated_at >= item_ops.get((name, key), ("", "", None))[0]:
                        item_ops[(name, key)] = (updated_at, "add", None)
                for key in item_diff.get("removed") or []:
                    if updated_at >= item_ops.get((name, key), ("", "", None))[0]:
                        item_ops[(name, key)] = (updated_at, "remove", None)
                if item_diff.get("order_changed"):
                    if updated_at >= latest_orders.get(name, ("", []))[0]:
                        latest_orders[name] = (updated_at, items)
                        if playlist.get("name"):
                            desired_playlists.setdefault(name, {"name": playlist.get("name"), "items": []})

        for name, (_updated_at, op, playlist) in playlist_ops.items():
            if op == "remove":
                desired_playlists.pop(name, None)
            else:
                desired_playlists[name] = playlist

        for (name, key), (_updated_at, op, _value) in item_ops.items():
            playlist = desired_playlists.setdefault(name, {"name": name, "items": []})
            items = list(playlist.get("items") or [])
            if op == "remove":
                items = [item_key for item_key in items if item_key != key]
            elif key not in items:
                order = latest_orders.get(name, ("", []))[1]
                if key in order:
                    insert_at = len(items)
                    for index, ordered_key in enumerate(order):
                        if ordered_key == key:
                            insert_at = min(index, len(items))
                            break
                    items.insert(insert_at, key)
                else:
                    items.append(key)
            playlist["items"] = items
            desired_playlists[name] = playlist

        for name, (_updated_at, order) in latest_orders.items():
            playlist = desired_playlists.get(name)
            if not playlist:
                continue
            current_items = list(playlist.get("items") or [])
            ordered = [key for key in order if key in current_items]
            ordered.extend(key for key in current_items if key not in ordered)
            playlist["items"] = ordered

        logger.warning(
            "[USER_SYNC] Delta sync apply domain=playlists playlists=%s playlist_ops=%s item_ops=%s orders=%s",
            len(desired_playlists),
            len(playlist_ops),
            len(item_ops),
            len(latest_orders),
        )
        deleted_playlist_names = [
            name
            for name, (_updated_at, op, _playlist) in playlist_ops.items()
            if op == "remove" and name not in desired_playlists
        ]
        result = self._sync_user_playlists_to_payload(
            desired_playlists,
            participants,
            deleted_playlist_names,
        )
        result["delta"] = {
            "playlists": len(desired_playlists),
            "deleted_playlists": len(deleted_playlist_names),
            "playlist_ops": len(playlist_ops),
            "item_ops": len(item_ops),
            "order_changes": len(latest_orders),
        }
        logger.warning("[USER_SYNC] Delta sync done domain=playlists result=%s", result)
        return result

    def _snapshot_progress_callback(self, group_id: str, label: str, results: Dict[str, Any]):
        def callback(stage: str, index: int, total: int, server_id: str, user_id: str, state: Dict[str, Any] | None):
            if stage == "start":
                message = f"Analisi snapshot {label}: {index}/{total}"
            elif stage == "done":
                changed = "modificato" if state and state.get("changed") else "invariato"
                message = f"Analisi snapshot {label}: {index}/{total} ({changed})"
            elif stage == "error":
                message = f"Analisi snapshot {label}: errore su {index}/{total}"
            else:
                message = f"Analisi snapshot {label}: {index}/{total}"
            self._mark_group_sync_result(group_id, "running", message, results)

        return callback

    def _run_sync_step(
        self,
        group_id: str,
        group_name: str,
        results: Dict[str, Any],
        result_key: str,
        label: str,
        work: Callable[[], Dict[str, Any]],
    ) -> None:
        message = f"Sincronizzazione {label} in corso"
        logger.warning("[USER_SYNC] Step start group %s (%s): %s", group_name, group_id, label)
        self._mark_group_sync_result(group_id, "running", message, results)
        results[result_key] = work()
        logger.warning("[USER_SYNC] Step done group %s (%s): %s -> %s", group_name, group_id, label, results[result_key])

    def run_group_sync(self, group_id: str) -> Dict[str, Any]:
        logger.warning("[USER_SYNC] Requested manual sync for group %s", group_id)
        try:
            dashboard_data = self._get_users_dashboard_data()
            groups = dashboard_data.get("groups", [])
            group = next((item for item in groups if item.get("id") == group_id), None)
            if not group:
                message = "Gruppo non trovato o utenti Emby non caricati"
                logger.warning("[USER_SYNC] Cannot sync group %s: %s", group_id, message)
                self._mark_group_sync_result(group_id, "error", message, {})
                return {"ok": False, "error": message}

            result = self._sync_group(group)
            return {"ok": result.get("status") == "success", "result": result}
        except Exception as e:
            logger.exception("[USER_SYNC] Manual sync failed for group %s", group_id)
            self._mark_group_sync_result(group_id, "error", str(e), {})
            return {"ok": False, "error": str(e)}

    def run_auto_sync(self) -> None:
        """
        Executes auto-sync for all enabled groups.
        """
        logger.info("[AUTO_SYNC] Starting user auto-sync...")

        dashboard_data = self._get_users_dashboard_data()
        groups = dashboard_data.get("groups", [])

        count = 0
        for group in groups:
            if not group.get("auto_sync"):
                continue

            result = self._sync_group(group)
            if result.get("status") == "ignored":
                continue
            if result.get("status") in ("success", "skipped"):
                count += 1

        logger.info(f"[AUTO_SYNC] Completed. Processed {count} groups.")

    def _sync_group(self, group: Dict[str, Any]) -> Dict[str, Any]:
        gid = group["id"]
        group_name = group.get("name") or gid
        sync_type = group.get("sync_type", "merge")
        sync_resume = group.get("sync_resume", False)
        sync_playstate = group.get("sync_playstate", True)
        sync_config = group.get("sync_config", False)
        sync_library_access = group.get("sync_library_access", False)
        sync_favorites = group.get("sync_favorites", False)
        sync_playlists = group.get("sync_playlists", False)
        playstate_bootstrap_done = group.get("playstate_bootstrap_done", False)
        favorites_bootstrap_done = group.get("favorites_bootstrap_done", False)
        playlists_bootstrap_done = group.get("playlists_bootstrap_done", False)
        config_categories = group.get("config_categories") or None
        users = group.get("users", [])

        if len(users) < 2:
            message = "Meno di 2 utenti nel gruppo"
            logger.warning("[USER_SYNC] Skipping group %s (%s): %s", group_name, gid, message)
            self._mark_group_sync_result(gid, "skipped", message, {})
            return {"status": "skipped", "message": message}

        if not any([sync_playstate, sync_config, sync_library_access, sync_favorites, sync_playlists]):
            message = "Nessun dominio selezionato"
            logger.warning("[USER_SYNC] Skipping group %s (%s): %s", group_name, gid, message)
            self._mark_group_sync_result(gid, "skipped", message, {})
            return {"status": "skipped", "message": message}

        logger.warning("[USER_SYNC] Start group %s (%s) type=%s", group_name, gid, sync_type)
        self._mark_group_sync_result(gid, "running", f"Preparazione sync gruppo ({sync_type})", {})
        leaders = [u for u in users if u.get("is_leader")]
        if len(leaders) != 1:
            message = f"Leader non valido: trovati {len(leaders)} leader"
            logger.warning("[AUTO_SYNC] Skipping group %s (%s): %s", group.get("name"), gid, message)
            self._mark_group_sync_result(gid, "skipped", message, {})
            return {"status": "skipped", "message": message}

        targets = [(u["server_id"], u["user_id"]) for u in users]

        try:
            results = {}
            if sync_type == "merge":
                if sync_playstate:
                    def sync_playstate_work():
                        if playstate_bootstrap_done:
                            return self._run_playstate_delta_sync(
                                targets,
                                sync_resume,
                                progress_callback=self._snapshot_progress_callback(gid, "visti", results),
                            )
                        result = self._sync_merge_playstate(targets, sync_resume)
                        self._mark_group_bootstrap_done(gid, "playstate")
                        result["bootstrap"] = "additive"
                        return result
                    self._run_sync_step(gid, group_name, results, "playstate", "visti", sync_playstate_work)
                if sync_config:
                    self._run_sync_step(
                        gid,
                        group_name,
                        results,
                        "config",
                        "impostazioni",
                        lambda: self._run_latest_wins(
                            "settings",
                            targets,
                            self._sync_user_config,
                            config_categories,
                            progress_callback=self._snapshot_progress_callback(gid, "impostazioni", results),
                        ),
                    )
                if sync_library_access:
                    self._run_sync_step(
                        gid,
                        group_name,
                        results,
                        "library_access",
                        "librerie",
                        lambda: self._run_latest_wins(
                            "settings",
                            targets,
                            self._sync_library_access,
                            progress_callback=self._snapshot_progress_callback(gid, "librerie", results),
                        ),
                    )
                if sync_favorites:
                    def sync_favorites_work():
                        if favorites_bootstrap_done:
                            return self._run_favorites_delta_sync(
                                targets,
                                progress_callback=self._snapshot_progress_callback(gid, "preferiti", results),
                            )
                        result = self._sync_merge_favorites(targets)
                        self._mark_group_bootstrap_done(gid, "favorites")
                        result["bootstrap"] = "additive"
                        return result
                    self._run_sync_step(gid, group_name, results, "favorites", "preferiti", sync_favorites_work)
                if sync_playlists:
                    def sync_playlists_work():
                        if playlists_bootstrap_done:
                            return self._run_playlists_delta_sync(
                                targets,
                                progress_callback=self._snapshot_progress_callback(gid, "playlist", results),
                            )
                        result = self._sync_merge_playlists(targets)
                        self._mark_group_bootstrap_done(gid, "playlists")
                        result["bootstrap"] = "additive"
                        return result
                    self._run_sync_step(gid, group_name, results, "playlists", "playlist", sync_playlists_work)
                logger.info("[AUTO_SYNC] Merge result for %s: %s", group["name"], results)

            elif sync_type == "one_way":
                leader = leaders[0]
                source_server_id = leader["server_id"]
                source_user_id = leader["user_id"]
                dest_targets = [
                    (t[0], t[1]) for t in targets
                    if not (t[0] == source_server_id and t[1] == source_user_id)
                ]

                if dest_targets:
                    if sync_playstate:
                        self._run_sync_step(
                            gid,
                            group_name,
                            results,
                            "playstate",
                            "visti",
                            lambda: self._sync_user_playstate_exact(source_server_id, source_user_id, dest_targets, sync_resume),
                        )
                    if sync_config:
                        self._run_sync_step(
                            gid,
                            group_name,
                            results,
                            "config",
                            "impostazioni",
                            lambda: self._sync_user_config(source_server_id, source_user_id, dest_targets, config_categories),
                        )
                    if sync_library_access:
                        self._run_sync_step(
                            gid,
                            group_name,
                            results,
                            "library_access",
                            "librerie",
                            lambda: self._sync_library_access(source_server_id, source_user_id, dest_targets),
                        )
                    if sync_favorites:
                        self._run_sync_step(
                            gid,
                            group_name,
                            results,
                            "favorites",
                            "preferiti",
                            lambda: self._sync_user_favorites_exact(source_server_id, source_user_id, dest_targets),
                        )
                    if sync_playlists:
                        self._run_sync_step(
                            gid,
                            group_name,
                            results,
                            "playlists",
                            "playlist",
                            lambda: self._sync_user_playlists_exact(source_server_id, source_user_id, dest_targets),
                        )
                    logger.info("[AUTO_SYNC] One-way result for %s: %s", group["name"], results)

            logger.warning("[USER_SYNC] Step start group %s (%s): snapshot", group_name, gid)
            self._mark_group_sync_result(gid, "running", "Aggiornamento snapshot sync", results)
            refresh_sync_states(
                self._state_tracker,
                targets,
                "auto-sync",
                sync_config=sync_config,
                sync_library_access=sync_library_access,
                sync_playstate=sync_playstate,
                sync_favorites=sync_favorites,
                sync_playlists=sync_playlists,
            )
            logger.warning("[USER_SYNC] Step done group %s (%s): snapshot", group_name, gid)

            enabled_domains = [
                label for label, enabled in [
                    ("visti", sync_playstate),
                    ("impostazioni", sync_config),
                    ("librerie", sync_library_access),
                    ("preferiti", sync_favorites),
                    ("playlist", sync_playlists),
                ]
                if enabled
            ]
            message = "Sincronizzati: " + ", ".join(enabled_domains) if enabled_domains else "Nessun dominio selezionato"
            self._mark_group_sync_result(gid, "success", message, results)
            logger.warning("[USER_SYNC] Completed group %s (%s): %s", group_name, gid, message)
            return {"status": "success", "message": message, "results": results}
        except Exception as e:
            logger.exception("[USER_SYNC] Error processing group %s (%s)", group_name, gid)
            self._mark_group_sync_result(gid, "error", str(e), {})
            return {"status": "error", "message": str(e)}
