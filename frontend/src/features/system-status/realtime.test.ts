import { describe, expect, it } from "vitest";

import {
  isSystemStatusRealtimeEvent,
  systemStatusRefreshDelayMs,
  systemStatusSectionsForEvent,
} from "@/features/system-status/realtime";

describe("system status realtime routing", () => {
  it("refreshes Event Bridge and Guard after a plugin update", () => {
    const event = { MessageType: "OctoHubsEventBridgeUpdated" };

    expect(systemStatusSectionsForEvent(event)).toEqual([
      "event-bridge",
      "transcode-guard",
    ]);
  });

  it("refreshes Emby status after connection and session updates", () => {
    expect(systemStatusSectionsForEvent({ MessageType: "ConnectionClosed" })).toEqual(["emby"]);
    expect(systemStatusSectionsForEvent({ MessageType: "SessionsUpdate" })).toEqual(["emby"]);
    expect(isSystemStatusRealtimeEvent({ MessageType: "RefreshProgress" })).toBe(false);
  });

  it("refreshes only the affected areas after configuration changes", () => {
    expect(systemStatusSectionsForEvent({
      MessageType: "OctoHubsConfigurationUpdated",
      Data: { scope: "servers" },
    })).toEqual(["emby", "event-bridge", "transcode-guard"]);
    expect(systemStatusSectionsForEvent({
      MessageType: "OctoHubsConfigurationUpdated",
      Data: { scope: "services" },
    })).toEqual(["database", "services"]);
    expect(systemStatusSectionsForEvent({
      MessageType: "OctoHubsConfigurationUpdated",
      Data: { scope: "automations" },
    })).toEqual([]);
  });

  it("keeps an explicit zero refresh interval manual", () => {
    expect(systemStatusRefreshDelayMs()).toBe(60_000);
    expect(systemStatusRefreshDelayMs(5)).toBe(5_000);
    expect(systemStatusRefreshDelayMs(0)).toBeNull();
    expect(systemStatusRefreshDelayMs(-1)).toBeNull();
  });
});
