import { describe, expect, it } from "vitest";

import { hasDifferentLinkNames, linkRequestPayload, linkSelectionsFromGroups, linkTargetGroups, needsLinkTargetChoice, preferredLinkLeaderKey } from "@/features/users/link-user-association";
import { userSelectionKey } from "@/features/users/presentation";
import type { EmbyUser, EmbyUserGroup } from "@/features/users/types";

const roy: EmbyUser = { server_id: "green", server_name: "Green", user_id: "roy", name: "Roy", is_disabled: false, is_user_disabled: false, is_remote_disabled: false, enable_remote_access: true, is_admin: false, is_leader: true };
const marta: EmbyUser = { ...roy, server_id: "purple", server_name: "Purple", user_id: "marta", name: "Marta", is_leader: false };

describe("link user association", () => {
  it("offers the linked destination when the selection includes a standalone user", () => {
    const groups: EmbyUserGroup[] = [
      { id: "linked", name: "Condiviso", is_linked: true, users: [roy] },
      { id: "unlinked-marta", name: "Marta", is_linked: false, users: [marta] },
    ];
    const selections = linkSelectionsFromGroups(groups, new Set([userSelectionKey(roy), userSelectionKey(marta)]));

    expect(linkTargetGroups(selections)).toEqual([{ id: "linked", name: "Condiviso" }]);
    expect(needsLinkTargetChoice(selections)).toBe(true);
  });

  it("keeps the legacy new-group flow for one existing group", () => {
    const groups: EmbyUserGroup[] = [{ id: "linked", name: "Condiviso", is_linked: true, users: [roy, marta] }];
    const selections = linkSelectionsFromGroups(groups, new Set([userSelectionKey(roy), userSelectionKey(marta)]));

    expect(needsLinkTargetChoice(selections)).toBe(false);
    expect(preferredLinkLeaderKey(selections)).toBe(userSelectionKey(roy));
    expect(hasDifferentLinkNames(selections)).toBe(true);
  });

  it("sends the chosen leader for a new group and preserves the leader of a reused group", () => {
    const groups: EmbyUserGroup[] = [
      { id: "linked", name: "Condiviso", is_linked: true, users: [roy] },
      { id: "unlinked-marta", name: "Marta", is_linked: false, users: [marta] },
    ];
    const selections = linkSelectionsFromGroups(groups, new Set([userSelectionKey(roy), userSelectionKey(marta)]));

    expect(linkRequestPayload({ selections, leaderKey: userSelectionKey(marta) }).links.map((link) => link.is_leader)).toEqual([false, true]);
    expect(linkRequestPayload({ selections, targetGroupId: "linked" }).links.map((link) => link.is_leader)).toEqual([true, false]);
  });
});
