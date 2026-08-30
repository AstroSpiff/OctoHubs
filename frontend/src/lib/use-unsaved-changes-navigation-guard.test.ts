import { describe, expect, it } from "vitest";

import { isPageNavigation } from "@/lib/use-unsaved-changes-navigation-guard";

describe("unsaved changes navigation guard", () => {
  it("does not treat a tab or focus change as leaving the current page", () => {
    expect(isPageNavigation("/configuration", "/configuration")).toBe(false);
    expect(isPageNavigation("/research", "/research")).toBe(false);
  });

  it("protects navigation to another workspace", () => {
    expect(isPageNavigation("/configuration", "/operations")).toBe(true);
  });
});
