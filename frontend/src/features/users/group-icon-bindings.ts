import { userIconTargetId } from "@/features/user-icons/presentation";
import type { SaveIconBindingInput } from "@/features/user-icons/types";
import type { EmbyUserGroup } from "@/features/users/types";

function groupIconBindingTargets(
  group: EmbyUserGroup,
  profileId: string,
): SaveIconBindingInput[] {
  if (group.is_linked) {
    return [{ targetType: "group", targetId: group.id, profileId }];
  }

  return group.users.map((user) => ({
    targetType: "user" as const,
    targetId: userIconTargetId(user),
    profileId,
  }));
}

function hasPendingGroupIconBinding(
  group: EmbyUserGroup,
  pendingBindings: SaveIconBindingInput[] | undefined,
) {
  if (!pendingBindings?.length) return false;
  const targetKeys = new Set(
    groupIconBindingTargets(group, "").map(
      (target) => `${target.targetType}:${target.targetId}`,
    ),
  );
  return pendingBindings.some((binding) =>
    targetKeys.has(`${binding.targetType}:${binding.targetId}`),
  );
}

export { groupIconBindingTargets, hasPendingGroupIconBinding };
