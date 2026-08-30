import { describe, expect, it } from "vitest";

import {
  isSecondaryNavigationItemActive,
  researchNavigation,
} from "@/features/navigation/secondary-navigation";

describe("isSecondaryNavigationItemActive", () => {
  it("distinguishes sibling destinations through their route", () => {
    const [independent, summary, rules] = researchNavigation;

    expect(isSecondaryNavigationItemActive(independent, "/research/rules", "")).toBe(false);
    expect(isSecondaryNavigationItemActive(summary, "/research/rules", "")).toBe(false);
    expect(isSecondaryNavigationItemActive(rules, "/research/rules", "")).toBe(true);
  });
});
