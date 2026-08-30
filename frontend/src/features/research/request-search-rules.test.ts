import { describe, expect, it } from "vitest";

import { appendRequestRuleTerm, defaultRequestRule } from "@/features/research/request-search-rules";

describe("request search rules", () => {
  it("inherits missing options from global search rules", () => {
    const rule = defaultRequestRule(
      { id: 12, rules: { query_terms: ["2160p"] } },
      { use_original_title: false, use_alt_titles_original: true, use_alt_titles_language: true, alt_titles_language: "en" },
    );

    expect(rule).toMatchObject({ request_id: 12, query_terms: "2160p", use_original_title: false, use_alt_titles_original: true, use_alt_titles_language: true, alt_titles_language: "en" });
  });

  it("adds a selected term once while preserving the existing rule", () => {
    const rule = defaultRequestRule({ id: 12, rules: { filter_terms: ["x265"] } }, {});
    expect(appendRequestRuleTerm(rule, "filter_terms", "HDR").filter_terms).toBe("x265, HDR");
    expect(appendRequestRuleTerm(rule, "filter_terms", "x265")).toBe(rule);
  });
});
