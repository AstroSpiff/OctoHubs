import { describe, expect, it } from "vitest";

import {
  probePath,
  probeScopeFromHash,
  probeScopeFromRoute,
} from "@/features/probe/probe-navigation";

describe("probe navigation", () => {
  it("normalizes the URL used by tabs and the sidebar submenu", () => {
    expect(probeScopeFromHash("#libraries")).toBe("libraries");
    expect(probeScopeFromHash("#unknown")).toBe("recent");
    expect(probeScopeFromRoute("libraries")).toBe("libraries");
    expect(probeScopeFromRoute("missing")).toBe("recent");
    expect(probePath("libraries")).toBe("/probe/libraries");
  });
});
