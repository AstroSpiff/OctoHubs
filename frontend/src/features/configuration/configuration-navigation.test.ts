import { describe, expect, it } from "vitest";

import { configurationTabHasDraft } from "@/features/configuration/configuration-draft-guard";
import {
  configurationPath,
  configurationTabAtOffset,
  configurationTabFromHash,
  configurationTabFromRoute,
} from "@/features/configuration/configuration-navigation";

describe("configuration navigation", () => {
  it("uses the matching legacy hash when it is valid", () => {
    expect(configurationTabFromHash("#event-bridge")).toBe("event-bridge");
    expect(configurationTabFromHash("#emby-servers")).toBe("servers");
    expect(configurationTabFromHash("#missing")).toBe("system-status");
    expect(configurationTabFromRoute("services")).toBe("services");
    expect(configurationTabFromRoute("missing")).toBe("system-status");
    expect(configurationPath("services")).toBe("/configuration/services");
  });

  it("wraps keyboard navigation through the complete tab list", () => {
    expect(configurationTabAtOffset("system-status", -1)).toBe("accounts");
    expect(configurationTabAtOffset("accounts", 1)).toBe("system-status");
  });

  it("protects only the tabs that can contain unsaved form drafts", () => {
    expect(configurationTabHasDraft("servers")).toBe(true);
    expect(configurationTabHasDraft("telegram")).toBe(true);
    expect(configurationTabHasDraft("automations")).toBe(true);
    expect(configurationTabHasDraft("services")).toBe(true);
    expect(configurationTabHasDraft("event-bridge")).toBe(true);
  });
});
