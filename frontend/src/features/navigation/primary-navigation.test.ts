import { describe, expect, it } from "vitest";

import { primaryNavigation } from "@/features/navigation/primary-navigation";

describe("primaryNavigation", () => {
  it("keeps every primary workspace directly reachable", () => {
    expect(primaryNavigation.map((item) => item.to)).toEqual([
      "/research/independent",
      "/emby-live",
      "/collections",
      "/probe/recent",
      "/configuration/system-status",
    ]);
  });

  it("exposes the local Research and Probe destinations to every navigation mode", () => {
    expect(primaryNavigation.find((item) => item.id === "research")?.secondary?.map((item) => item.to)).toEqual([
      "/research/independent",
      "/research/summary",
      "/research/rules",
      "/research/requests",
    ]);
    expect(primaryNavigation.find((item) => item.id === "probe")?.secondary?.map((item) => item.to)).toEqual([
      "/probe/recent",
      "/probe/libraries",
    ]);
  });
});
