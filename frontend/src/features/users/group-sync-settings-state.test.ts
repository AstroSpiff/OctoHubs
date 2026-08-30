import { describe, expect, it } from "vitest";

import {
  groupSyncSettingsFrom,
  groupSyncSettingsMatch,
} from "@/features/users/group-sync-settings-state";

describe("groupSyncSettingsMatch", () => {
  it("compares editable sync options without treating category order as a change", () => {
    const saved = groupSyncSettingsFrom({
      id: "friends",
      name: "Amici",
      is_linked: true,
      users: [],
      sync_type: "merge",
      sync_playstate: true,
      config_categories: ["profile", "display"],
    });

    expect(
      groupSyncSettingsMatch(saved, {
        ...saved,
        config_categories: ["display", "profile"],
      }),
    ).toBe(true);
    expect(
      groupSyncSettingsMatch(saved, { ...saved, sync_favorites: true }),
    ).toBe(false);
  });
});
