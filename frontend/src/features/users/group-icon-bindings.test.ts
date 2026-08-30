import { describe, expect, it } from "vitest";

import {
  groupIconBindingTargets,
  hasPendingGroupIconBinding,
} from "@/features/users/group-icon-bindings";
import type { EmbyUserGroup } from "@/features/users/types";

const linkedGroup = {
  id: "group-1",
  name: "Famiglia",
  is_linked: true,
  users: [],
} as EmbyUserGroup;
const standaloneGroup = {
  id: "single-1",
  name: "Anna",
  is_linked: false,
  users: [
    {
      server_id: "green",
      user_id: "anna",
      name: "Anna",
    },
  ],
} as EmbyUserGroup;

describe("group icon bindings", () => {
  it("uses a group binding for linked users and individual bindings otherwise", () => {
    expect(groupIconBindingTargets(linkedGroup, "family")).toEqual([
      { targetType: "group", targetId: "group-1", profileId: "family" },
    ]);
    expect(groupIconBindingTargets(standaloneGroup, "solo")).toEqual([
      { targetType: "user", targetId: "green:anna", profileId: "solo" },
    ]);
  });

  it("marks only the group whose icon bindings are being saved", () => {
    const pending = groupIconBindingTargets(linkedGroup, "family");

    expect(hasPendingGroupIconBinding(linkedGroup, pending)).toBe(true);
    expect(hasPendingGroupIconBinding(standaloneGroup, pending)).toBe(false);
  });
});
