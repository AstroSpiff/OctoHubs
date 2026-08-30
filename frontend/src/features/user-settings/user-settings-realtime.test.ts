import { describe, expect, it } from "vitest";

import { isSettingsPresetRealtimeEvent } from "@/features/user-settings/user-settings-realtime";

describe("user settings realtime events", () => {
  it("refreshes presets only for a matching OctoHubs update", () => {
    expect(
      isSettingsPresetRealtimeEvent({
        MessageType: "OctoHubsUsersUpdated",
        Data: { scope: "presets" },
      }),
    ).toBe(true);
    expect(
      isSettingsPresetRealtimeEvent({
        MessageType: "OctoHubsUsersUpdated",
        Data: { scope: "settings" },
      }),
    ).toBe(false);
  });
});
