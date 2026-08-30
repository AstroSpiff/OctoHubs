import { describe, expect, it } from "vitest";

import { duplicateCloneGroupNames } from "@/features/users/clone-group-warning";
import type { EmbyUser, EmbyUserGroup } from "@/features/users/types";

const anna = {
  server_id: "green",
  user_id: "anna",
  name: "Anna",
} as EmbyUser;
const luca = {
  server_id: "purple",
  user_id: "luca",
  name: "Luca",
} as EmbyUser;
const groups = [
  { id: "family", name: "Famiglia", is_linked: true, users: [anna, luca] },
  { id: "single", name: "Marco", is_linked: false, users: [anna] },
] as EmbyUserGroup[];

describe("clone group warning", () => {
  it("warns only when multiple selected users share a linked group", () => {
    expect(duplicateCloneGroupNames([anna, luca], groups)).toEqual([
      "Famiglia",
    ]);
    expect(duplicateCloneGroupNames([anna], groups)).toEqual([]);
  });
});
