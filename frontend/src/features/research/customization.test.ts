// @vitest-environment jsdom

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  customRulesFromStoredValue,
  customRulesStorageKey,
  loadStoredCustomRules,
  storeCustomRules,
} from "@/features/research/customization";
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
  beforeEach(() => window.localStorage.clear());
  afterEach(() => vi.restoreAllMocks());

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

  it("isolates enabled drafts by authenticated account", () => {
    const accountOne = { ...fallback, exclude_tags: ["account-one"] };
    const accountTwo = { ...fallback, exclude_tags: ["account-two"] };
    storeCustomRules(11, true, accountOne);
    storeCustomRules(22, false, accountTwo);

    expect(loadStoredCustomRules(11, fallback)).toEqual({
      enabled: true,
      value: accountOne,
    });
    expect(loadStoredCustomRules(22, fallback)).toEqual({
      enabled: false,
      value: accountTwo,
    });
    expect(customRulesStorageKey(11)).not.toBe(customRulesStorageKey(22));
  });

  it("does not attribute the unowned legacy draft to the next account", () => {
    window.localStorage.setItem("indie-search-rules", JSON.stringify({
      enabled: true,
      rules: { ...fallback, exclude_tags: ["previous-account"] },
    }));

    expect(loadStoredCustomRules(33, fallback)).toEqual({
      enabled: false,
      value: fallback,
    });
    expect(window.localStorage.getItem("indie-search-rules")).toBeNull();
    expect(window.localStorage.getItem(customRulesStorageKey(33) || "")).toBeNull();
  });

  it("does not read or write account rules while the session has no owner", () => {
    storeCustomRules(null, true, { ...fallback, exclude_tags: ["anonymous"] });

    expect(loadStoredCustomRules(null, fallback)).toEqual({
      enabled: false,
      value: fallback,
    });
    expect(Object.keys(window.localStorage)).toEqual([]);
  });

  it("discards a corrupt account draft without affecting another account", () => {
    const corruptKey = customRulesStorageKey(44);
    const validRules = { ...fallback, exclude_tags: ["valid"] };
    if (!corruptKey) throw new Error("missing test key");
    window.localStorage.setItem(corruptKey, "{not-json");
    storeCustomRules(55, true, validRules);

    expect(loadStoredCustomRules(44, fallback)).toEqual({
      enabled: false,
      value: fallback,
    });
    expect(window.localStorage.getItem(corruptKey)).toBeNull();
    expect(loadStoredCustomRules(55, fallback).value.exclude_tags).toEqual(["valid"]);
  });

  it.each(["removeItem", "getItem"] as const)(
    "fails closed when browser storage.%s throws",
    (method) => {
      vi.spyOn(Storage.prototype, method).mockImplementation(() => {
        throw new DOMException("storage denied", "SecurityError");
      });

      expect(loadStoredCustomRules(66, fallback)).toEqual({
        enabled: false,
        value: fallback,
      });
    },
  );

  it("keeps the in-memory editor usable when browser storage writes throw", () => {
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new DOMException("quota exceeded", "QuotaExceededError");
    });

    expect(() => storeCustomRules(77, true, fallback)).not.toThrow();
  });
});
