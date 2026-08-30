import { request } from "@/lib/http";
import type { UserSettings } from "@/features/user-settings/types";
import { linkRequestPayload } from "@/features/users/link-user-association";
import type { BulkCloneInput, BulkCloneResult, CloneUserInput, EmbyUser, EmbyUserDetails, EmbyUserGroup, LinkUsersInput, PasswordTarget, SaveGroupSyncSettingsInput, UserActionResult, UsersDashboard } from "@/features/users/types";

export function getUsersDashboard(): Promise<UsersDashboard> {
  return request<UsersDashboard>("/api/v1/emby/users/list");
}

export function getUserDetails(user: EmbyUser): Promise<EmbyUserDetails> {
  return request<EmbyUserDetails>(`/api/v1/emby/users/${encodeURIComponent(user.server_id)}/${encodeURIComponent(user.user_id)}/details`);
}

export function toggleRemoteAccess(user: EmbyUser): Promise<UserActionResult> {
  return request<UserActionResult>("/api/v1/emby/users/toggle-remote", {
    method: "POST",
    body: JSON.stringify({
      server_id: user.server_id,
      user_id: user.user_id,
      enable: !user.enable_remote_access,
    }),
  });
}

export function toggleDownloadAccess(user: EmbyUser): Promise<UserActionResult> {
  return request<UserActionResult>("/api/v1/emby/users/toggle-download", {
    method: "POST",
    body: JSON.stringify({
      server_id: user.server_id,
      user_id: user.user_id,
      enable: !user.enable_downloading,
    }),
  });
}

export function syncUserGroup(groupId: string): Promise<UserActionResult> {
  return request<UserActionResult>("/api/v1/emby/users/group/sync-now", {
    method: "POST",
    body: JSON.stringify({ group_id: groupId }),
  });
}

export function saveGroupSyncSettings(input: SaveGroupSyncSettingsInput): Promise<UserActionResult> {
  return request<UserActionResult>("/api/v1/emby/users/group/settings", { method: "POST", body: JSON.stringify(input) });
}

export function linkUsers({ selections, targetGroupId, leaderKey }: LinkUsersInput): Promise<UserActionResult> {
  const payload = linkRequestPayload({ selections, targetGroupId, leaderKey });
  return request<UserActionResult>("/api/v1/emby/users/link", {
    method: "POST",
    body: JSON.stringify({ links: payload.links, group_id: payload.targetGroupId }),
  });
}

export function setGroupLeader(group: EmbyUserGroup, leader: EmbyUser): Promise<UserActionResult> {
  return request<UserActionResult>("/api/v1/emby/users/link", {
    method: "POST",
    body: JSON.stringify({
      group_id: group.id,
      links: group.users.map((user) => ({
        server_id: user.server_id,
        user_id: user.user_id,
        username: user.name,
        is_leader: user.server_id === leader.server_id && user.user_id === leader.user_id,
      })),
    }),
  });
}

export function unlinkUser(user: EmbyUser): Promise<UserActionResult> {
  return request<UserActionResult>("/api/v1/emby/users/unlink", {
    method: "POST",
    body: JSON.stringify({ server_id: user.server_id, user_id: user.user_id }),
  });
}

export function renameUser({ user, name }: { user: EmbyUser; name: string }): Promise<UserActionResult> {
  return request<UserActionResult>("/api/v1/emby/users/rename", {
    method: "POST",
    body: JSON.stringify({ server_id: user.server_id, user_id: user.user_id, new_name: name }),
  });
}

export function renameGroup({ groupId, name }: { groupId: string; name: string }): Promise<UserActionResult> {
  return request<UserActionResult>("/api/v1/emby/users/group/rename", {
    method: "POST",
    body: JSON.stringify({ group_id: groupId, new_name: name }),
  });
}

export function savePassword({ target, password }: { target: PasswordTarget; password: string }): Promise<UserActionResult> {
  if (target.scope === "group") {
    return request<UserActionResult>("/api/v1/emby/users/password-group", {
      method: "POST",
      body: JSON.stringify({ group_id: target.groupId, new_password: password }),
    });
  }
  return request<UserActionResult>("/api/v1/emby/users/password", {
    method: "POST",
    body: JSON.stringify({
      server_id: target.serverId,
      user_id: target.userId,
      new_password: password,
    }),
  });
}

export function getPasswordInfo(target: PasswordTarget): Promise<{ ok: boolean; saved: boolean; password?: string | null; updated_at?: string | null }> {
  const params = new URLSearchParams(target.scope === "group" ? { group_id: target.groupId } : { server_id: target.serverId, user_id: target.userId });
  return request<{ ok: boolean; saved: boolean; password?: string | null; updated_at?: string | null }>(`/api/v1/emby/users/password?${params.toString()}`);
}

export function deleteUser({ user, expectedName }: { user: EmbyUser; expectedName: string }): Promise<UserActionResult> {
  return request<UserActionResult>("/api/v1/emby/users/delete", { method: "POST", body: JSON.stringify({ server_id: user.server_id, user_id: user.user_id, expected_name: expectedName }) });
}

export function deleteGroupUsers({ group, expectedName }: { group: EmbyUserGroup; expectedName: string }): Promise<UserActionResult> {
  return request<UserActionResult>("/api/v1/emby/users/group/delete-users", { method: "POST", body: JSON.stringify({ group_id: group.id, expected_name: expectedName }) });
}

export function cloneUser(input: CloneUserInput): Promise<UserActionResult> {
  return request<UserActionResult>("/api/v1/emby/users/clone", {
    method: "POST",
    body: JSON.stringify({
      source_server_id: input.source.server_id,
      source_user_id: input.source.user_id,
      target_server_id: input.targetServerId,
      new_username: input.newUsername,
      sync_config: input.syncConfig,
      sync_playstate: input.syncPlaystate,
      sync_resume: input.syncResume,
      sync_library_access: input.syncLibraryAccess,
      sync_favorites: input.syncFavorites,
      sync_playlists: input.syncPlaylists,
      link_group: input.linkGroup,
      config_categories: input.configCategories,
    }),
  });
}

export async function cloneUsers(input: BulkCloneInput): Promise<BulkCloneResult> {
  const failed: BulkCloneResult["failed"] = [];
  let completed = 0;

  for (const source of input.sources) {
    for (const targetServerId of input.targetServerIds) {
      if (targetServerId === source.user.server_id) continue;
      try {
        await cloneUser({
          source: source.user,
          targetServerId,
          newUsername: source.newUsername,
          syncConfig: input.syncConfig,
          syncPlaystate: input.syncPlaystate,
          syncResume: input.syncPlaystate && input.syncResume,
          syncLibraryAccess: input.syncLibraryAccess,
          syncFavorites: input.syncFavorites,
          syncPlaylists: input.syncPlaylists,
          linkGroup: source.linkGroup,
          configCategories: input.configCategories,
        });
        completed += 1;
      } catch (reason) {
        failed.push({
          source: source.user,
          targetServerId,
          message: reason instanceof Error ? reason.message : "Clonazione non riuscita",
        });
      }
    }
  }

  if (!completed && failed.length) throw new Error(failed.map((item) => item.message).join("; "));
  return { completed, failed };
}

export function checkUserName(serverId: string, username: string): Promise<{ exists: boolean }> {
  return request<{ exists: boolean }>("/api/v1/emby/users/check", {
    method: "POST",
    body: JSON.stringify({ server_id: serverId, username }),
  });
}

export function applySettingsToUsers({ users, settings, applyLibraries }: { users: EmbyUser[]; settings: UserSettings; applyLibraries: boolean }): Promise<UserActionResult> {
  return request<UserActionResult>("/api/v1/emby/users/settings-apply", {
    method: "POST",
    body: JSON.stringify({
      targets: users.map((user) => ({ server_id: user.server_id, user_id: user.user_id })),
      settings,
      apply_libraries: applyLibraries,
    }),
  });
}

export function createUsers({ username, password, serverIds, linkGroup, presetId }: { username: string; password: string; serverIds: string[]; linkGroup: boolean; presetId?: string | null }): Promise<UserActionResult> {
  return request<UserActionResult>("/api/v1/emby/users/create", {
    method: "POST",
    body: JSON.stringify({ targets: serverIds.map((server_id) => ({ server_id, username })), preset_id: presetId || null, password, link_group: linkGroup, group_name: username }),
  });
}
