import type { UserIconConfig } from "@/features/user-icons/types";
import type { EmbyUser, EmbyUserGroup } from "@/features/users/types";

export function iconImageUrl(path: string, revision: number): string {
  const base = path.startsWith("/api/emby/icons/image/")
    ? `/api/v1${path.slice(4)}`
    : path.startsWith("/")
      ? path
      : `/static/${path}`;
  return `${base}?v=${revision}`;
}

export function iconBindingKey(targetType: "group" | "user", targetId: string): string {
  return `${targetType}:${targetId}`;
}

export function userIconTargetId(user: EmbyUser): string {
  return `${user.server_id}:${user.user_id}`;
}

export function userAvatarUrl(
  group: EmbyUserGroup,
  user: EmbyUser,
  config: UserIconConfig,
  revision: number,
): string | undefined {
  const profileId = group.is_linked
    ? config.bindings[iconBindingKey("group", group.id)]
    : config.bindings[iconBindingKey("user", userIconTargetId(user))];
  const sourceServerId = group.is_linked
    ? (group.users.find((member) => member.is_leader)?.server_id || group.users[0]?.server_id)
    : user.server_id;
  const iconPath = profileId && sourceServerId
    ? config.matrix[profileId]?.[sourceServerId]
    : undefined;

  return iconPath ? iconImageUrl(iconPath, revision) : user.image_url;
}
