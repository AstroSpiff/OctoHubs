import { userSelectionKey } from "@/features/users/presentation";
import type { EmbyUserGroup, LinkUsersInput, LinkUserSelection } from "@/features/users/types";

export type LinkTargetGroup = { id: string; name: string };

export function linkSelectionsFromGroups(groups: EmbyUserGroup[], selectedKeys: ReadonlySet<string>): LinkUserSelection[] {
  return groups.flatMap((group) => group.users
    .filter((user) => selectedKeys.has(userSelectionKey(user)))
    .map((user) => ({
      user,
      groupId: group.id,
      groupName: group.name,
      groupIsLinked: group.is_linked,
    })));
}

export function linkTargetGroups(selections: LinkUserSelection[]): LinkTargetGroup[] {
  const groups = new Map<string, LinkTargetGroup>();
  selections.forEach((selection) => {
    if (selection.groupIsLinked) groups.set(selection.groupId, { id: selection.groupId, name: selection.groupName });
  });
  return [...groups.values()];
}

export function needsLinkTargetChoice(selections: LinkUserSelection[], targets = linkTargetGroups(selections)) {
  return targets.length > 1 || (targets.length === 1 && selections.some((selection) => !selection.groupIsLinked));
}

export function preferredLinkLeaderKey(selections: LinkUserSelection[]) {
  const preferred = selections.find(({ user }) => !user.is_user_disabled && !user.is_disabled) || selections[0];
  return preferred ? userSelectionKey(preferred.user) : "";
}

export function hasDifferentLinkNames(selections: LinkUserSelection[]) {
  const names = new Set(selections.map(({ user }) => normalizeLinkName(user.name)).filter(Boolean));
  return names.size > 1;
}

export function linkRequestPayload({ selections, targetGroupId, leaderKey }: LinkUsersInput) {
  return {
    targetGroupId,
    links: selections.map(({ user, groupId }) => ({
      server_id: user.server_id,
      user_id: user.user_id,
      username: user.name,
      is_leader: targetGroupId ? groupId === targetGroupId && user.is_leader : userSelectionKey(user) === leaderKey,
    })),
  };
}

function normalizeLinkName(value: string) {
  return value.trim().toLocaleLowerCase("it").replace(/[^a-z0-9]/g, "");
}
