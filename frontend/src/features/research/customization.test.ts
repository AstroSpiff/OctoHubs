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
      enabled: false,
      value: fallback,
    });
  });

  it("restores an explicitly enabled local override", () => {
    expect(customRulesFromStoredValue(fallback, {
      enabled: true,
      rules: {
        search_rules: { min_seeders: 9 },
        target_languages: ["ita", "italian"],
        exclude_tags: ["ts"],
      },
    })).toEqual({
      enabled: true,
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

  it("keeps legacy rules as a disabled draft", () => {
    expect(customRulesFromStoredValue(fallback, {
      search_rules: { min_seeders: 7 },
      target_languages: ["eng"],
    })).toEqual({
      enabled: false,
      value: {
        search_rules: {
          query_terms: ["2160p"],
          min_seeders: 7,
          use_original_title: false,
        },
        target_languages: ["eng"],
        exclude_tags: [],
      },
    });
  });
});
