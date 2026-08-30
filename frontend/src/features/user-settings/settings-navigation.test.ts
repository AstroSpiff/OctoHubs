import { describe, expect, it } from "vitest";

import {
  settingsScopeAtOffset,
  settingsScopes,
} from "@/features/user-settings/settings-navigation";

describe("user settings navigation", () => {
  it("keeps every settings scope available in the editor", () => {
    expect(settingsScopes).toEqual([
      "policy",
      "config",
      "display_preferences",
    ]);
  });

  it("wraps keyboard navigation across the available scopes", () => {
    expect(settingsScopeAtOffset("policy", -1)).toBe("display_preferences");
    expect(settingsScopeAtOffset("display_preferences", 1)).toBe("policy");
  });
});
