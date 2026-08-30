import { describe, expect, it } from "vitest";

import { selectedAvailableProbeServerId } from "@/features/probe/probe-server-selection";

const servers = [{ id: "green" }, { id: "purple" }];

describe("selectedAvailableProbeServerId", () => {
  it("keeps a currently available server", () => {
    expect(selectedAvailableProbeServerId("purple", servers)).toBe("purple");
  });

  it("falls back to the first available server when the previous one disappears", () => {
    expect(selectedAvailableProbeServerId("removed", servers)).toBe("green");
  });

  it("returns an empty selection when there are no available servers", () => {
    expect(selectedAvailableProbeServerId("green", [])).toBe("");
  });
});
