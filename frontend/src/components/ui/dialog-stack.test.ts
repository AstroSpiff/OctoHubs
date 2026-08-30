import { describe, expect, it } from "vitest";

import { isTopmostDialog } from "@/components/ui/dialog-stack";

describe("dialog stack", () => {
  it("lets only the most recently opened dialog receive keyboard controls", () => {
    const editor = {};
    const sources = {};
    const confirmation = {};

    expect(isTopmostDialog([editor, sources, confirmation], confirmation)).toBe(true);
    expect(isTopmostDialog([editor, sources, confirmation], sources)).toBe(false);
    expect(isTopmostDialog([editor, sources, confirmation], editor)).toBe(false);
  });

  it("does not consider a detached dialog active", () => {
    const editor = {};

    expect(isTopmostDialog([editor], null)).toBe(false);
  });
});
