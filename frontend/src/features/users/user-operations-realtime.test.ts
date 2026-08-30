import { describe, expect, it } from "vitest";

import { isUserOperationsRealtimeEvent } from "@/features/users/user-operations-realtime";

describe("user operations realtime events", () => {
  it("updates the operation center only for its own application events", () => {
    expect(
      isUserOperationsRealtimeEvent({
        MessageType: "OctoHubsUsersUpdated",
        Data: { scope: "operations" },
      }),
    ).toBe(true);
    expect(
      isUserOperationsRealtimeEvent({
        MessageType: "OctoHubsUsersUpdated",
        Data: { scope: "sync" },
      }),
    ).toBe(false);
  });
});
