import { describe, expect, it } from "vitest";

import {
  normalizeUserSettings,
  updateSettingsValue,
  userSettingsMatch,
} from "@/features/user-settings/settings-model";

describe("user settings model", () => {
  it("keeps every settings scope when a single field changes", () => {
    const settings = normalizeUserSettings({ policy: { IsAdministrator: false }, config: { AudioLanguagePreference: "ita" } });
    expect(updateSettingsValue(settings, "policy", "IsAdministrator", true)).toEqual({ ...settings, policy: { IsAdministrator: true } });
  });

  it("compares nested settings without being affected by object key order", () => {
    const saved = normalizeUserSettings({
      policy: { AllowDownloads: true, MaxSessions: 2 },
      libraries: { mode: "custom", items: ["movies"], groups: { a: 1, b: 2 } },
    });

    expect(
      userSettingsMatch(saved, {
        ...saved,
        policy: { MaxSessions: 2, AllowDownloads: true },
        libraries: { ...saved.libraries, groups: { b: 2, a: 1 } },
      }),
    ).toBe(true);
    expect(
      userSettingsMatch(saved, {
        ...saved,
        libraries: { ...saved.libraries, items: ["tvshows"] },
      }),
    ).toBe(false);
  });
});
