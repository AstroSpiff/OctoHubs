import { describe, expect, it } from "vitest";

import { customRulesFromStoredValue } from "@/features/research/customization";
import type { CustomSearchRules } from "@/features/research/types";

const fallback: CustomSearchRules = {
  search_rules: {
    query_terms: ["2160p"],
    min_seeders: 4,
    use_original_title: false,
  },
  target_languages: ["ita"],
  exclude_tags: ["cam"],
};

describe("stored independent-search rules", () => {
  it("keeps the default rules when browser storage is empty", () => {
    expect(customRulesFromStoredValue(fallback, null)).toEqual({
      found: false,
      value: fallback,
    });
  });

  it("merges a stored local override and marks it as active", () => {
    expect(customRulesFromStoredValue(fallback, {
      search_rules: { min_seeders: 9 },
      target_languages: ["ita", "italian"],
      exclude_tags: ["ts"],
    })).toEqual({
      found: true,
      value: {
        search_rules: {
          query_terms: ["2160p"],
          min_seeders: 9,
          use_original_title: false,
        },
        target_languages: ["ita", "italian"],
        exclude_tags: ["ts"],
      },
    });
  });
});
