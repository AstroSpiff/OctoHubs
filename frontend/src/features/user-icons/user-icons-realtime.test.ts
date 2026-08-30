import { describe, expect, it } from "vitest";

import { isUserIconsRealtimeEvent } from "@/features/user-icons/user-icons-realtime";

describe("user icon realtime events", () => {
  it("refreshes only for icon configuration updates", () => {
    expect(isUserIconsRealtimeEvent({ MessageType: "OctoHubsUsersUpdated", Data: { scope: "icons" } })).toBe(true);
    expect(isUserIconsRealtimeEvent({ MessageType: "OctoHubsUsersUpdated", Data: { scope: "dashboard" } })).toBe(false);
    expect(isUserIconsRealtimeEvent({ MessageType: "ConfigurationUpdated", Data: { scope: "icons" } })).toBe(false);
  });
});
