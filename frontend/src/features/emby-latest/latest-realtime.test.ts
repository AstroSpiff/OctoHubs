import { describe, expect, it } from "vitest";

import {
  latestRealtimeTargets,
  latestUpdatedMessage,
} from "@/features/emby-latest/latest-realtime";

describe("Latest Publications realtime", () => {
  it("separates configuration changes from publication data changes", () => {
    expect(
      latestRealtimeTargets({
        MessageType: latestUpdatedMessage,
        Data: { scope: "configuration" },
      }),
    ).toEqual(["configuration"]);
    expect(
      latestRealtimeTargets({
        MessageType: latestUpdatedMessage,
        Data: { scope: "snapshot" },
      }),
    ).toEqual(["snapshot"]);
  });

  it("updates the available servers when their shared configuration changes", () => {
    expect(
      latestRealtimeTargets({
        MessageType: "OctoHubsConfigurationUpdated",
        Data: { scope: "servers" },
      }),
    ).toEqual(["configuration", "snapshot"]);
  });
});
