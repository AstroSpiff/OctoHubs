import { userSelectionKey } from "@/features/users/presentation";
import type { EmbyUser, EmbyUserGroup } from "@/features/users/types";

function duplicateCloneGroupNames(
  users: EmbyUser[],
  groups: EmbyUserGroup[],
) {
  const selectedUserKeys = new Set(users.map(userSelectionKey));

  return groups
    .filter(
      (group) =>
        group.is_linked &&
        group.users.filter((user) => selectedUserKeys.has(userSelectionKey(user)))
          .length > 1,
    )
    .map((group) => group.name);
}

export { duplicateCloneGroupNames };
