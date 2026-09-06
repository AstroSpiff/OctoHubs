import { describe, expect, it } from "vitest";

import { guardActionForTarget, hasAuthoritativeGuardState } from "@/features/transcode-guard/guard-state";

describe("Transcode Guard authoritative state", () => {
  it.each([
    ["initial loading", undefined, null, false],
    ["initial error", undefined, new Error("offline"), false],
    ["stale snapshot after a refresh error", { running: true }, new Error("offline"), false],
    ["successful snapshot", { running: false }, null, true],
  ])("classifies %s", (_label, snapshot, error, expected) => {
    expect(hasAuthoritativeGuardState(snapshot, error)).toBe(expected);
  });

  it("derives the command from the user's requested target, not cached state", () => {
    expect(guardActionForTarget(true)).toBe("start");
    expect(guardActionForTarget(false)).toBe("stop");
  });
});
