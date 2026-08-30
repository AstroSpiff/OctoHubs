import { describe, expect, it } from "vitest";

import { isEventBridgeUpdate } from "@/features/event-bridge/use-event-bridge-realtime";

describe("Event Bridge realtime events", () => {
  it("refreshes only for Event Bridge state updates", () => {
    expect(isEventBridgeUpdate({ MessageType: "OctoHubsEventBridgeUpdated" })).toBe(true);
    expect(isEventBridgeUpdate({ MessageType: "RefreshProgress" })).toBe(false);
  });
});
