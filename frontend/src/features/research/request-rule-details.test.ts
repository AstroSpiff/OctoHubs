import { describe, expect, it } from "vitest";

import { requestRuleDetailsOpenForWidth } from "@/features/research/request-rule-details";

describe("request rule details", () => {
  it("keeps rules open on spacious layouts", () => {
    expect(requestRuleDetailsOpenForWidth(1_101)).toBe(true);
  });

  it("starts collapsed at the compact breakpoint", () => {
    expect(requestRuleDetailsOpenForWidth(1_100)).toBe(false);
    expect(requestRuleDetailsOpenForWidth(640)).toBe(false);
  });
});
