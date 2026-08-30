import type { Severity } from "@/components/ui/badge";
import type { EmbyUser, EmbyUserGroup, UsersFilters } from "@/features/users/types";

export const defaultUsersFilters: UsersFilters = {
  search: "",
  groupType: "all",
  serverIds: [],
  statuses: [],
  iconProfileIds: [],
  sort: "name_asc_server_asc",
};

export function userSelectionKey(user: EmbyUser) {
  return `${user.server_id}:${user.user_id}`;
}

export function replaceVisibleUserSelection(selected: Iterable<string>, visibleUsers: EmbyUser[], nextVisibleUsers: EmbyUser[]) {
  const visibleKeys = new Set(visibleUsers.map(userSelectionKey));
  const next = new Set([...selected].filter((key) => !visibleKeys.has(key)));
  nextVisibleUsers.forEach((user) => next.add(userSelectionKey(user)));
  return next;
}

export function clearVisibleUserSelection(selected: Iterable<string>, visibleUsers: EmbyUser[]) {
  const visibleKeys = new Set(visibleUsers.map(userSelectionKey));
  return new Set([...selected].filter((key) => !visibleKeys.has(key)));
}

export function groupVisibleUsers(
  group: EmbyUserGroup,
  filters: UsersFilters,
  bindings: Record<string, string> = {},
) {
  const query = filters.search.trim().toLocaleLowerCase("it");
  return group.users.filter((user) => {
    if (filters.serverIds.length && !filters.serverIds.includes(user.server_id)) return false;
    if (filters.statuses.length && !filters.statuses.some((status) => matchesAccessStatus(user, status))) return false;
    if (!matchesUserIconProfile(group, user, filters.iconProfileIds, bindings)) return false;
    if (!query) return true;
    return [group.name, user.name, user.server_alias, user.server_name].filter(Boolean).some((value) => String(value).toLocaleLowerCase("it").includes(query));
  });
}

export function visibleUserGroups(groups: EmbyUserGroup[], filters: UsersFilters, bindings: Record<string, string> = {}) {
  const filtered = groups
    .filter((group) => filters.groupType === "all" || (filters.groupType === "linked" ? group.is_linked : !group.is_linked))
    .map((group) => ({ ...group, users: groupVisibleUsers(group, filters, bindings) }))
    .filter((group) => group.users.length);
  return filtered.sort((left, right) => {
    if (left.is_owners !== right.is_owners) return left.is_owners ? 1 : -1;
    if (filters.sort === "members") return right.users.length - left.users.length || left.name.localeCompare(right.name, "it");
    return compareUserGroups(left, right, filters.sort);
  });
}

function matchesUserIconProfile(
  group: EmbyUserGroup,
  user: EmbyUser,
  selectedProfiles: string[],
  bindings: Record<string, string>,
) {
  if (!selectedProfiles.length) return true;
  const profileId = group.is_linked
    ? bindings[`group:${group.id}`] || ""
    : bindings[`user:${userSelectionKey(user)}`] || "";
  return (selectedProfiles.includes("none") && !profileId) || selectedProfiles.includes(profileId);
}

export function isLeaderOrStandalone(group: EmbyUserGroup, user: EmbyUser) {
  return user.is_leader || !group.is_linked;
}

export function accessPresentation(user: EmbyUser): { label: string; severity: Severity } {
  if (user.is_user_disabled) return { label: "Account disabilitato", severity: "error" };
  if (user.is_remote_disabled || !user.enable_remote_access) return { label: "Remoto disabilitato", severity: "warning" };
  return { label: "Attivo", severity: "ok" };
}

export function syncPresentation(group: EmbyUserGroup): { label: string; severity: Severity } {
  if (!group.is_linked) return { label: group.is_owners ? "Proprietari" : "Non associato", severity: "neutral" };
  if (group.last_sync_status === "running") return { label: "Sincronizzazione", severity: "info" };
  if (["error", "failed", "interrupted"].includes(String(group.last_sync_status))) return { label: "Errore di sincronizzazione", severity: "error" };
  if (group.last_sync_status === "skipped") return { label: "Sincronizzazione da verificare", severity: "warning" };
  if (group.auto_sync !== true) return { label: "Automazione disattivata", severity: "neutral" };
  if (["success", "completed"].includes(String(group.last_sync_status))) return { label: "Sincronizzato", severity: "ok" };
  return { label: group.last_sync_at ? "Da sincronizzare" : "Mai sincronizzato", severity: "neutral" };
}

type SavedState = {
  password_status?: string;
  password_saved?: boolean;
  password_mismatch?: boolean;
  settings_status?: string;
  settings_saved?: boolean;
  settings_mismatch?: boolean;
};

type ManagedState = { label: string; severity: Severity };

export function passwordPresentation(item: Pick<SavedState, "password_status" | "password_saved" | "password_mismatch">): ManagedState {
  const status = item.password_status || (item.password_mismatch ? "mismatch" : item.password_saved ? "saved" : "missing");
  if (status === "mismatch") return { label: "Password non allineata", severity: "warning" };
  if (status === "saved") return { label: "Password salvata", severity: "ok" };
  return { label: "Password non salvata", severity: "error" };
}

export function settingsPresentation(item: Pick<SavedState, "settings_status" | "settings_saved" | "settings_mismatch">): ManagedState {
  const status = item.settings_status || (item.settings_mismatch ? "mismatch" : item.settings_saved ? "saved" : "missing");
  if (status === "mismatch") return { label: "Impostazioni non allineate", severity: "warning" };
  if (status === "saved") return { label: "Impostazioni salvate", severity: "ok" };
  return { label: "Impostazioni non salvate", severity: "error" };
}

export function formatUserTime(value?: string | null) {
  const date = value ? new Date(value) : null;
  return date && !Number.isNaN(date.getTime()) ? new Intl.DateTimeFormat("it-IT", { dateStyle: "medium", timeStyle: "medium" }).format(date) : "Mai";
}

function groupServerName(group: EmbyUserGroup) {
  const user = group.users.find((item) => item.is_leader) || group.users[0];
  return user?.server_alias || user?.server_name || "";
}

function compareUserGroups(left: EmbyUserGroup, right: EmbyUserGroup, sort: Exclude<UsersFilters["sort"], "members">) {
  const name = left.name.localeCompare(right.name, "it");
  const server = groupServerName(left).localeCompare(groupServerName(right), "it");
  const descendingName = sort.includes("name_desc");
  const descendingServer = sort.includes("server_desc");
  const nameOrder = descendingName ? -name : name;
  const serverOrder = descendingServer ? -server : server;

  return sort.startsWith("server_") ? serverOrder || nameOrder : nameOrder || serverOrder;
}

function matchesAccessStatus(user: EmbyUser, status: string) {
  if (status === "active") return !user.is_user_disabled && !user.is_remote_disabled && user.enable_remote_access;
  if (status === "remote_disabled") return !user.is_user_disabled && (user.is_remote_disabled || !user.enable_remote_access);
  if (status === "account_disabled") return user.is_user_disabled;
  return true;
}
