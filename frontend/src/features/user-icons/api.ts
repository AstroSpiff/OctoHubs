import { request } from "@/lib/http";
import type { SaveIconBindingInput, SaveIconProfileInput, UserIconConfig } from "@/features/user-icons/types";

export function getUserIconConfig(): Promise<UserIconConfig> {
  return request<UserIconConfig>("/api/v1/emby/icons/config");
}

export function saveIconProfile(input: SaveIconProfileInput): Promise<{ ok: boolean; profile_id: string }> {
  return request<{ ok: boolean; profile_id: string }>("/api/v1/emby/icons/profile", {
    method: "POST",
    body: JSON.stringify({
      profile_id: input.id || "",
      label: input.label,
      is_group_profile: input.isGroupProfile,
    }),
  });
}

export function deleteIconProfile(profileId: string): Promise<{ ok: boolean }> {
  return request<{ ok: boolean }>("/api/v1/emby/icons/profile", {
    method: "DELETE",
    body: JSON.stringify({ profile_id: profileId }),
  });
}

export function saveIconBinding({ targetType, targetId, profileId }: SaveIconBindingInput): Promise<{ ok: boolean }> {
  return request<{ ok: boolean }>("/api/v1/emby/icons/binding", {
    method: "POST",
    body: JSON.stringify({
      target_type: targetType,
      target_id: targetId,
      profile_id: profileId,
    }),
  });
}

export function uploadIconRule({ profileId, serverId, file }: { profileId: string; serverId: string; file: File }): Promise<{ ok: boolean }> {
  const body = new FormData();
  body.set("profile_id", profileId);
  body.set("column_key", serverId);
  body.set("file", file);
  return request<{ ok: boolean }>("/api/v1/emby/icons/rule", { method: "POST", body });
}

export function deleteIconRule({ profileId, serverId }: { profileId: string; serverId: string }): Promise<{ ok: boolean }> {
  return request<{ ok: boolean }>("/api/v1/emby/icons/rule", {
    method: "DELETE",
    body: JSON.stringify({ profile_id: profileId, column_key: serverId }),
  });
}
