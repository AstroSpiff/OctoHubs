import { describe, expect, it } from "vitest";

import {
  formatSettingsUpdatedAt,
  settingsEditorStatus,
} from "@/features/user-settings/settings-editor-status";

describe("settingsEditorStatus", () => {
  it("keeps group and user alignment problems visible", () => {
    expect(
      settingsEditorStatus(
        { scope: "group", groupId: "family", name: "Famiglia", mismatchCount: 2 },
        { saved: true },
      ),
    ).toMatchObject({ tone: "warning", label: "Impostazioni salvate, 2 utenti non allineati" });
    expect(
      settingsEditorStatus(
        { scope: "user", serverId: "green", userId: "roy", name: "Roy", mismatch: true },
        { saved: true },
      ),
    ).toMatchObject({ tone: "warning" });
  });

  it("formats a valid timestamp to the second and ignores invalid values", () => {
    expect(formatSettingsUpdatedAt("2026-08-15T09:12:35.249429+00:00")).toMatch(/\d{2}:\d{2}:35/);
    expect(formatSettingsUpdatedAt("not-a-date")).toBeNull();
  });
});
