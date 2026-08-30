import { describe, expect, it } from "vitest";

import {
  collectionRealtimeTargets,
  isCollectionsRealtimeEvent,
} from "@/features/collections/collections-realtime";

describe("collections realtime events", () => {
  it("refreshes only the collection data affected by an update", () => {
    expect(
      collectionRealtimeTargets({
        MessageType: "OctoHubsCollectionsUpdated",
        Data: { scope: "definitions" },
      }),
    ).toEqual(["collections"]);
    expect(
      collectionRealtimeTargets({
        MessageType: "OctoHubsCollectionsUpdated",
        Data: { scope: "sources" },
      }),
    ).toEqual(["source-inventory"]);
    expect(
      collectionRealtimeTargets({
        MessageType: "OctoHubsCollectionsUpdated",
        Data: { scope: "unknown" },
      }),
    ).toEqual([]);
  });

  it("also refreshes collection options after relevant configuration changes", () => {
    expect(
      collectionRealtimeTargets({
        MessageType: "OctoHubsConfigurationUpdated",
        Data: { scope: "servers" },
      }),
    ).toEqual(["collections", "options"]);
    expect(
      collectionRealtimeTargets({
        MessageType: "OctoHubsConfigurationUpdated",
        Data: { scope: "services" },
      }),
    ).toEqual(["options"]);
    expect(isCollectionsRealtimeEvent({ MessageType: "RefreshProgress" })).toBe(
      false,
    );
  });
});
