import { userIconTargetId } from "@/features/user-icons/presentation";
import type { SaveIconBindingInput } from "@/features/user-icons/types";
import { iconBindingOperationKey } from "@/features/user-icons/use-keyed-operation-state";
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
  pendingKeys: ReadonlySet<string>,
) {
  return groupIconBindingTargets(group, "").some((target) =>
    pendingKeys.has(iconBindingOperationKey(target.targetType, target.targetId)),
  );
}

export { groupIconBindingTargets, hasPendingGroupIconBinding };
