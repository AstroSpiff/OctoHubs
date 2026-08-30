import { describe, expect, it } from "vitest";

import {
  createUserDraft,
  createUserDraftMatches,
} from "@/features/users/create-user-draft";

describe("create user draft", () => {
  const servers = [
    { id: "green", name: "Green" },
    { id: "purple", name: "Purple" },
  ];

  it("starts with all available servers selected", () => {
    expect(createUserDraft(servers)).toMatchObject({
      serverIds: ["green", "purple"],
      linkGroup: true,
    });
  });

  it("compares selected servers as a set, not as a click order", () => {
    const draft = createUserDraft(servers);

    expect(
      createUserDraftMatches(draft, { ...draft, serverIds: ["purple", "green"] }),
    ).toBe(true);
    expect(
      createUserDraftMatches(draft, { ...draft, username: "Anna" }),
    ).toBe(false);
  });
});
