import { describe, expect, it } from "vitest";

import { boundedWholeNumberInput } from "@/lib/numeric-input";

describe("boundedWholeNumberInput", () => {
  it("uses bounded whole values matching backend integer normalization", () => {
    expect(boundedWholeNumberInput("121", 2, 120)).toBe(120);
    expect(boundedWholeNumberInput("1.9", 2, 120)).toBe(2);
    expect(boundedWholeNumberInput("", 0, 3650)).toBe(0);
  });

  it("supports settings that only need a lower bound", () => {
    expect(boundedWholeNumberInput("3.8", 1)).toBe(3);
    expect(boundedWholeNumberInput("0", 1)).toBe(1);
  });
});
