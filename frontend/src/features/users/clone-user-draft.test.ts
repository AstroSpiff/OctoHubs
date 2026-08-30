import { describe, expect, it } from "vitest";

import {
  cloneUserDraft,
  cloneUserDraftMatches,
} from "@/features/users/clone-user-draft";
import type { EmbyUser } from "@/features/users/types";

const user = {
  server_id: "green",
  user_id: "anna",
  name: "Anna",
} as EmbyUser;
const servers = [
  { id: "green", name: "Green" },
  { id: "purple", name: "Purple" },
];

describe("clone user draft", () => {
  it("does not offer the source server as a target for a single clone", () => {
    expect(cloneUserDraft([user], servers)).toMatchObject({
      targetServerIds: ["purple"],
      sources: [{ linkGroup: false }],
    });
  });

  it("detects changes while ignoring the order of selected targets", () => {
    const draft = cloneUserDraft([user], servers);

    expect(
      cloneUserDraftMatches(draft, { ...draft, targetServerIds: [...draft.targetServerIds] }),
    ).toBe(true);
    expect(
      cloneUserDraftMatches(draft, {
        ...draft,
        sources: [{ ...draft.sources[0], newUsername: "Anna copia" }],
      }),
    ).toBe(false);
  });
});
