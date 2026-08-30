import { describe, expect, it } from "vitest";

import { isUserRelatedEmbyEvent } from "@/features/users/use-users-realtime";

describe("users realtime events", () => {
  it("refreshes users only for user-related Emby events", () => {
    expect(isUserRelatedEmbyEvent({ MessageType: "UserPolicyUpdated", Data: {} })).toBe(true);
    expect(isUserRelatedEmbyEvent({ MessageType: "Sessions", Data: { UserId: "user-1" } })).toBe(true);
    expect(isUserRelatedEmbyEvent({ MessageType: "LibraryChanged", Data: { ItemId: "item-1" } })).toBe(false);
  });
});
