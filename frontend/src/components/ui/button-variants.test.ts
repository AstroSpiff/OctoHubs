import { describe, expect, it } from "vitest";

import { buttonVariants } from "@/components/ui/button-variants";

describe("button variants", () => {
  it("lets text buttons grow when a compact label wraps", () => {
    for (const size of ["default", "compact"] as const) {
      const classes = buttonVariants({ size });
      expect(classes).toContain("app-button");
      expect(classes).toContain("app-button--text");
      expect(classes).toContain("whitespace-normal");
      expect(classes).toContain("text-center");
      expect(classes).toContain("leading-[1.1]");
      expect(classes).toContain("min-h-[var(--control-height");
      expect(classes).not.toMatch(/(?:^|\s)h-\[/);
    }
  });

  it("exposes the size class used by the shared control scale", () => {
    expect(buttonVariants({ size: "default" })).toContain("app-button--default");
    expect(buttonVariants({ size: "compact" })).toContain("app-button--compact");
  });

  it("keeps icon-only buttons square and prevents wrapping", () => {
    const classes = buttonVariants({ size: "icon" });
    expect(classes).toContain("app-button--icon");
    expect(classes).toContain("h-[var(--control-height-compact)]");
    expect(classes).toContain("w-[var(--control-height-compact)]");
    expect(classes).toContain("whitespace-nowrap");
  });
});
