"""Mutation workflows for Emby user settings."""

from __future__ import annotations

import logging
from typing import Any, Callable, Dict, List, Optional, Tuple

from emby_users.operation_progress import emit_progress
from emby_users.mutation_coordinator import group_sync_key, user_mutation_keys
from emby_users.settings_target_applier import SettingsApplyOptions, SettingsApplyResult
from core.log_sanitization import format_exception_for_log

logger = logging.getLogger(__name__)


class SettingsApplyMixin:
    def _apply_settings_to_user(
        self,
        server_id: str,
        user_id: str,
        settings: Dict[str, Any],
        library_index: Dict[str, Dict[str, List[str]]],
        libraries_by_server: Dict[str, Dict[str, Any]],
        membership: Optional[Dict[str, Dict[str, str]]] = None,
        display_source_server_id: Optional[str] = None,
        preserve_non_group: bool = False
    ) -> Tuple[bool, bool, bool]:
        normalized = self._normalize_settings_payload(settings)
        result = self._apply_normalized_settings_to_user(
            server_id,
            user_id,
            normalized,
            library_index,
            libraries_by_server,
            membership=membership,
            display_source_server_id=display_source_server_id,
            preserve_non_group=preserve_non_group,
        )
        return result.policy_ok, result.config_ok, result.display_ok

    def _apply_normalized_settings_to_user(
        self,
        server_id: str,
        user_id: str,
        normalized: Dict[str, Any],
        library_index: Dict[str, Dict[str, List[str]]],
        libraries_by_server: Dict[str, Dict[str, Any]],
        membership: Optional[Dict[str, Dict[str, str]]] = None,
        display_source_server_id: Optional[str] = None,
        preserve_non_group: bool = False,
        apply_libraries: bool = True,
    ) -> SettingsApplyResult:
        return self._target_applier.apply(
            server_id,
            user_id,
            normalized,
            library_index,
            libraries_by_server,
            membership=membership,
            options=SettingsApplyOptions(
                apply_libraries=apply_libraries,
                preserve_non_group_libraries=preserve_non_group,
                display_source_server_id=display_source_server_id,
            ),
        )

    def apply_config_sync_patch_to_user(
        self,
        server_id: str,
        user_id: str,
        settings: Dict[str, Any],
        source_server_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Apply a source-filtered config patch without altering library access."""
        with self._mutation_coordinator.guard(user_mutation_keys(server_id, user_id)) as acquired:
            if not acquired:
                return {"ok": False, "busy": True, "error": "Operazione utente già in corso"}
            return self._apply_config_sync_patch_to_user_guarded(
                server_id,
                user_id,
                settings,
                source_server_id,
            )

    def _apply_config_sync_patch_to_user_guarded(
        self,
        server_id: str,
        user_id: str,
        settings: Dict[str, Any],
        source_server_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        normalized = self._normalize_settings_payload(settings)
        if normalized.get("display_preferences"):
            _, library_index, libraries_by_server, membership = self._build_library_group_index()
        else:
            library_index = {}
            libraries_by_server = {}
            membership = {}
        result = self._apply_normalized_settings_to_user(
            server_id,
            user_id,
            normalized,
            library_index,
            libraries_by_server,
            membership=membership,
            display_source_server_id=source_server_id,
            apply_libraries=False,
        )
        return {
            "ok": result.ok,
            "policy": result.policy_ok,
            "config": result.config_ok,
            "display_preferences": result.display_ok,
            "policy_error": result.policy_error,
            "config_error": result.config_error,
            "display_error": result.display_error,
            "fetch_error": result.fetch_error,
        }

    def apply_settings_to_users(
        self,
        targets: List[Dict[str, Any]],
        settings: Dict[str, Any],
        apply_libraries: bool = False,
        progress_callback: Optional[Callable[[Dict[str, Any]], None]] = None
    ) -> Dict[str, Any]:
        target_list = list(targets or [])
        keys = [
            key
            for target in target_list
            if isinstance(target, dict) and target.get("server_id") and target.get("user_id")
            for key in user_mutation_keys(
                str(target.get("server_id") or ""),
                str(target.get("user_id") or ""),
            )
        ]
        with self._mutation_coordinator.guard(keys) as acquired:
            if not acquired:
                return {
                    "ok": False,
                    "busy": True,
                    "success": [],
                    "failed": ["Un'altra operazione sugli utenti selezionati è in corso"],
                    "counts": {},
                }
            return self._apply_settings_to_users_guarded(
                target_list,
                settings,
                apply_libraries,
                progress_callback,
            )

    def _apply_settings_to_users_guarded(
        self,
        targets: List[Dict[str, Any]],
        settings: Dict[str, Any],
        apply_libraries: bool = False,
        progress_callback: Optional[Callable[[Dict[str, Any]], None]] = None,
    ) -> Dict[str, Any]:
        persistence_keys = {
            (
                str(target.get("server_id") or ""),
                str(target.get("user_id") or ""),
            ): self.settings_user_key(
                str(target.get("server_id") or ""),
                str(target.get("user_id") or ""),
            )
            for target in targets
            if isinstance(target, dict) and target.get("server_id") and target.get("user_id")
        }
        _, library_index, libraries_by_server, membership = self._build_library_group_index()
        normalized = self._normalize_settings_payload(settings, protect_fields=True)
        policy_patch = normalized.get("policy") or {}
        config_patch = normalized.get("config") or {}
        display_patch = normalized.get("display_preferences") or {}
        results = {"success": [], "failed": [], "counts": {}}
        target_list = list(targets or [])
        total = len(target_list)
        emit_progress(progress_callback, "start", "Preparazione applicazione impostazioni", 0, total)

        for index, target in enumerate(target_list, start=1):
            server_id = str(target.get("server_id") or "")
            user_id = str(target.get("user_id") or "")
            if not server_id or not user_id:
                results["failed"].append("Target non valido")
                emit_progress(progress_callback, "target", "Target non valido", index, total)
                continue

            server = self._get_server_by_id(server_id)
            target_label = (
                target.get("username")
                or target.get("name")
                or (server.get("alias") or server.get("name") if server else None)
                or f"{server_id}/{user_id}"
            )
            emit_progress(
                progress_callback,
                "target",
                f"Applico impostazioni a {target_label}",
                index - 1,
                total,
                {"server_id": server_id, "user_id": user_id, "target_label": target_label},
            )
            result = self._apply_normalized_settings_to_user(
                server_id,
                user_id,
                normalized,
                library_index,
                libraries_by_server,
                membership=membership,
                preserve_non_group=apply_libraries,
                apply_libraries=apply_libraries,
            )
            if not result.server:
                results["failed"].append(f"{target_label}: server non trovato")
                emit_progress(progress_callback, "target", f"Server non trovato: {target_label}", index, total)
                continue
            if not result.details:
                results["failed"].append(
                    f"{target_label}: impossibile leggere utente ({result.fetch_error})"
                )
                emit_progress(progress_callback, "target", f"Utente non leggibile: {target_label}", index, total)
                continue

            if result.ok:
                try:
                    snapshot = self._extract_settings_from_details(
                        {"Policy": result.policy or {}, "Configuration": result.config or {}},
                        server_id,
                        library_index,
                        result.display_payload
                    )
                    self._save_settings_entry(
                        persistence_keys[(server_id, user_id)], snapshot
                    )
                except Exception as exc:
                    logger.error(
                        "[SETTINGS] Local persistence failed after remote update for %s/%s:\n%s",
                        server_id,
                        user_id,
                        format_exception_for_log(exc),
                    )
                    results["failed"].append(
                        f"{target_label}: impostazioni applicate, persistenza locale non completata"
                    )
                    results["reconciliation_required"] = True
                    emit_progress(
                        progress_callback,
                        "target",
                        f"Persistenza impostazioni non riuscita: {target_label}",
                        index,
                        total,
                    )
                    continue
                results["success"].append(target_label)
                results["counts"][target_label] = {
                    "policy": len(policy_patch),
                    "config": len(config_patch),
                    "display_preferences": len(display_patch),
                    "libraries": bool(apply_libraries)
                }
                emit_progress(
                    progress_callback,
                    "target",
                    f"Impostazioni applicate a {target_label}",
                    index,
                    total,
                    {"server_id": server_id, "user_id": user_id, "target_label": target_label},
                )
            else:
                results["failed"].append(
                    f"{target_label}: policy={result.policy_ok} {result.policy_error or ''}, "
                    f"config={result.config_ok} {result.config_error or ''}, "
                    f"display={result.display_ok} {result.display_error or ''}"
                )
                emit_progress(progress_callback, "target", f"Errore impostazioni su {target_label}", index, total)

        results["ok"] = not results["failed"]
        results["status"] = (
            "success"
            if results["ok"]
            else "partial"
            if results["success"] or results.get("reconciliation_required")
            else "error"
        )
        emit_progress(
            progress_callback,
            "complete",
            f"Impostazioni applicate: {len(results['success'])}/{total}",
            total,
            total,
            {"success": len(results["success"]), "failed": len(results["failed"])},
        )
        return results

    def update_user_settings(self, server_id: str, user_id: str, settings: Dict[str, Any]) -> Dict[str, Any]:
        with self._mutation_coordinator.guard(user_mutation_keys(server_id, user_id)) as acquired:
            if not acquired:
                return {"ok": False, "busy": True, "error": "Operazione utente già in corso"}
            return self._update_user_settings_guarded(server_id, user_id, settings)

    def _update_user_settings_guarded(self, server_id: str, user_id: str, settings: Dict[str, Any]) -> Dict[str, Any]:
        persistence_key = self.settings_user_key(server_id, user_id)
        _, library_index, libraries_by_server, membership = self._build_library_group_index()
        normalized = self._normalize_settings_payload(settings)
        items = normalized.get("libraries", {}).get("items") or []
        groups = normalized.get("libraries", {}).get("groups") or {}
        if items and not groups:
            enabled_set = {str(x) for x in items if x}
            derived_groups: Dict[str, bool] = {}
            for group_key, servers in library_index.items():
                lib_ids = servers.get(server_id) or []
                if any(str(lib_id) in enabled_set for lib_id in lib_ids):
                    derived_groups[group_key] = True
            normalized["libraries"]["groups"] = derived_groups
        ok_p, ok_c, ok_d = self._apply_settings_to_user(
            server_id,
            user_id,
            normalized,
            library_index,
            libraries_by_server,
            membership=membership,
            display_source_server_id=server_id
        )
        if not ok_p or not ok_c or not ok_d:
            return {"ok": False, "error": "Update failed", "policy": ok_p, "config": ok_c, "display_preferences": ok_d}
        try:
            entry = self._save_settings_entry(
                persistence_key, normalized
            )
        except Exception as exc:
            logger.error(
                "[SETTINGS] Local persistence failed after remote update for %s/%s:\n%s",
                server_id,
                user_id,
                format_exception_for_log(exc),
            )
            return {
                "ok": False,
                "status": "partial",
                "applied": 1,
                "error": "Impostazioni applicate, persistenza locale non completata",
                "reconciliation_required": True,
            }
        logger.info("[SETTINGS] Saved user settings: %s/%s", server_id, user_id)
        return {"ok": True, "updated_at": entry.get("updated_at")}

    def sync_library_access(
        self,
        source_server_id: str,
        source_user_id: str,
        target_tuples: List[tuple]
    ) -> Dict[str, Any]:
        """
        Copy library access using configured library associations.

        Library IDs are server-specific, so this method copies source access by
        associated library group and then derives the target server's own IDs.
        """
        keys = [
            key
            for server_id, user_id in target_tuples
            for key in user_mutation_keys(server_id, user_id)
        ]
        with self._mutation_coordinator.guard(keys) as acquired:
            if not acquired:
                return {"ok": False, "busy": True, "error": "Operazione utenti già in corso"}
            return self._sync_library_access_guarded(source_server_id, source_user_id, target_tuples)

    def _sync_library_access_guarded(
        self,
        source_server_id: str,
        source_user_id: str,
        target_tuples: List[tuple],
    ) -> Dict[str, Any]:
        source_server = self._get_server_by_id(source_server_id)
        if not source_server:
            return {"error": "Source server not found"}

        source_details, err = self._fetch_user_details(source_server, source_user_id)
        if err or not source_details:
            return {"error": f"Failed to fetch source user: {err}"}

        _, library_index, libraries_by_server, membership = self._build_library_group_index()
        source_settings = self._extract_settings_from_details(source_details, source_server_id, library_index)
        source_libraries = source_settings.get("libraries") or {}
        source_mode = source_libraries.get("mode")
        source_groups = source_libraries.get("groups") or {}

        results = {
            "success": [],
            "failed": [],
            "counts": {},
            "missing_groups": {},
            "association_url": "/emby#association-card"
        }
        enabled_group_keys = [group_key for group_key, enabled in source_groups.items() if enabled]

        for target_server_id, target_user_id in target_tuples:
            target_server = self._get_server_by_id(target_server_id)
            target_label = (
                target_server.get("alias") or target_server.get("name") or target_server.get("id")
                if target_server else target_server_id
            )
            if not target_server:
                results["failed"].append(f"Server {target_server_id} not found")
                continue

            missing_groups = [
                group_key
                for group_key in enabled_group_keys
                if not library_index.get(group_key, {}).get(target_server_id)
            ]

            library_settings = {
                "mode": source_mode if source_mode in ("all", "custom") else "all",
                "groups": dict(source_groups),
                "items": []
            }
            normalized = {"policy": {}, "config": {}, "display_preferences": {}, "libraries": library_settings}
            ok_p, ok_c, ok_d = self._apply_settings_to_user(
                target_server_id,
                target_user_id,
                normalized,
                library_index,
                libraries_by_server,
                membership=membership,
                preserve_non_group=True
            )
            if ok_p and ok_c and ok_d:
                enabled_ids = []
                if library_settings["mode"] == "custom":
                    enabled_ids = self._derive_enabled_ids_from_groups(
                        source_groups,
                        library_index,
                        target_server_id
                    )
                results["success"].append(target_label)
                results["counts"][target_label] = len(enabled_ids) if library_settings["mode"] == "custom" else "all"
                results["missing_groups"][target_label] = missing_groups
            else:
                results["failed"].append(f"{target_label}: policy={ok_p}, config={ok_c}, display={ok_d}")

        return results

    def set_group_settings(self, group_id: str, settings: Dict[str, Any]) -> Dict[str, Any]:
        users = self._get_group_users(group_id)
        if not users:
            return {"ok": False, "error": "Group has no users", "group_id": group_id}
        keys = [
            group_sync_key(group_id),
            *(key for server_id, user_id, _ in users for key in user_mutation_keys(server_id, user_id)),
        ]
        with self._mutation_coordinator.guard(keys) as acquired:
            if not acquired:
                return {"ok": False, "busy": True, "error": "Operazione utenti già in corso", "group_id": group_id}
            current_users = self._get_group_users(group_id)
            if {(server_id, user_id) for server_id, user_id, _ in current_users} != {
                (server_id, user_id) for server_id, user_id, _ in users
            }:
                return {"ok": False, "busy": True, "error": "Il gruppo utenti è cambiato; riprova", "group_id": group_id}
            return self._set_group_settings_guarded(group_id, settings, current_users)

    def _set_group_settings_guarded(
        self,
        group_id: str,
        settings: Dict[str, Any],
        users: List[Tuple[str, str, Optional[str]]],
    ) -> Dict[str, Any]:
        group_persistence_key = self.settings_group_key(group_id)
        user_persistence_keys = {
            (server_id, user_id): self.settings_user_key(server_id, user_id)
            for server_id, user_id, _username in users
        }
        _, library_index, libraries_by_server, membership = self._build_library_group_index()
        normalized = self._normalize_settings_payload(settings, protect_fields=True)
        normalized["libraries"]["items"] = []
        try:
            entry = self._save_settings_entry(group_persistence_key, normalized)
        except Exception as exc:
            logger.error(
                "[SETTINGS] Group snapshot persistence failed before remote update for %s:\n%s",
                group_id,
                format_exception_for_log(exc),
            )
            return {
                "ok": False,
                "status": "error",
                "group_id": group_id,
                "applied": 0,
                "failed": [{
                    "group_id": group_id,
                    "stage": "persistence",
                    "error": "Impostazioni del gruppo non salvate",
                }],
                "reconciliation_required": False,
            }
        failures = []
        applied = 0
        for server_id, user_id, _ in users:
            ok_p, ok_c, ok_d = self._apply_settings_to_user(
                server_id,
                user_id,
                normalized,
                library_index,
                libraries_by_server,
                membership=membership,
                preserve_non_group=True
            )
            if ok_p and ok_c and ok_d:
                applied += 1
                try:
                    self._save_settings_entry(
                        user_persistence_keys[(server_id, user_id)], normalized
                    )
                except Exception as exc:
                    logger.error(
                        "[SETTINGS] Local persistence failed after group update for %s/%s:\n%s",
                        server_id,
                        user_id,
                        format_exception_for_log(exc),
                    )
                    failures.append({
                        "server_id": server_id,
                        "user_id": user_id,
                        "stage": "persistence",
                        "error": "Impostazioni applicate, persistenza locale non completata",
                    })
            else:
                failures.append({
                    "server_id": server_id,
                    "user_id": user_id,
                    "policy": ok_p,
                    "config": ok_c,
                    "display_preferences": ok_d
                })
        if failures:
            logger.error("[SETTINGS] Group update failed: %s", failures)
            return {
                "ok": False,
                "status": "partial" if applied else "error",
                "group_id": group_id,
                "applied": applied,
                "failed": failures,
                "reconciliation_required": bool(applied),
            }
        logger.info("[SETTINGS] Saved group settings: %s", group_id)
        return {"ok": True, "group_id": group_id, "applied": applied, "updated_at": entry.get("updated_at")}
