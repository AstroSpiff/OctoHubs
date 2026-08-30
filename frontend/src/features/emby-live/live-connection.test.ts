import { describe, expect, it } from "vitest";

import { liveConnectionFromHeartbeat } from "@/features/emby-live/live-connection";

describe("liveConnectionFromHeartbeat", () => {
  const staleAfterMilliseconds = 8_000;

  it("waits for a valid payload before declaring the feed connected", () => {
    expect(
      liveConnectionFromHeartbeat({
        connectedAt: 1_000,
        lastPayloadAt: 0,
        now: 1_500,
        staleAfterMilliseconds,
      }),
    ).toBe("loading");
  });

  it("marks a feed without fresh data as reconnecting", () => {
    expect(
      liveConnectionFromHeartbeat({
        connectedAt: 1_000,
        lastPayloadAt: 0,
        now: 9_001,
        staleAfterMilliseconds,
      }),
    ).toBe("reconnecting");
  });

  it("uses the last valid payload as the live heartbeat", () => {
    expect(
      liveConnectionFromHeartbeat({
        connectedAt: 1_000,
        lastPayloadAt: 5_000,
        now: 9_000,
        staleAfterMilliseconds,
      }),
    ).toBe("connected");
  });

  it("distinguishes a fresh HTTP fallback from the live feed", () => {
    expect(
      liveConnectionFromHeartbeat({
        connectedAt: 1_000,
        lastPayloadAt: 5_000,
        lastFallbackAt: 9_000,
        now: 14_000,
        staleAfterMilliseconds,
        fallbackStaleAfterMilliseconds: 6_000,
      }),
    ).toBe("fallback");
  });

  it("returns to reconnecting once neither transport has fresh data", () => {
    expect(
      liveConnectionFromHeartbeat({
        connectedAt: 1_000,
        lastPayloadAt: 5_000,
        lastFallbackAt: 9_000,
        now: 16_001,
        staleAfterMilliseconds,
        fallbackStaleAfterMilliseconds: 6_000,
      }),
    ).toBe("reconnecting");
  });
});
