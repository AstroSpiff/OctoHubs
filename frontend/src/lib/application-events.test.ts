import { describe, expect, it } from "vitest";

import {
  configurationUpdateScope,
  isEventBridgeUpdate,
} from "@/lib/application-events";

describe("application event routing", () => {
  it("recognizes only supported configuration update scopes", () => {
    expect(configurationUpdateScope({
      MessageType: "OctoHubsConfigurationUpdated",
      Data: { scope: "services" },
    })).toBe("services");
    expect(configurationUpdateScope({
      MessageType: "OctoHubsConfigurationUpdated",
      Data: { scope: "unknown" },
    })).toBeNull();
    expect(configurationUpdateScope({ MessageType: "RefreshProgress" })).toBeNull();
  });

  it("keeps Event Bridge updates separate from configuration updates", () => {
    expect(isEventBridgeUpdate({ MessageType: "OctoHubsEventBridgeUpdated" })).toBe(true);
    expect(isEventBridgeUpdate({ MessageType: "OctoHubsConfigurationUpdated" })).toBe(false);
  });
});
