import type { CustomSearchRules, ResearchSearchRules } from "@/features/research/types";

const customRulesStorageKey = "indie-search-rules";

function customRulesFromSearchRules(rules: ResearchSearchRules): CustomSearchRules {
  return {
    search_rules: {
      query_languages: arrayValue(rules.query_languages),
      query_terms: arrayValue(rules.query_terms),
      include_target_lang_base: Boolean(rules.include_target_lang_base),
      season_templates: arrayValue(rules.season_templates),
      filter_terms: arrayValue(rules.filter_terms),
      min_seeders: numberValue(rules.min_seeders),
      require_audio_language: Boolean(rules.require_audio_language),
      search_episode_variants: Boolean(rules.search_episode_variants),
      skip_season_queries_when_episode_search: Boolean(rules.skip_season_queries_when_episode_search),
      sanitize_titles: Boolean(rules.sanitize_titles),
      ignore_year_for_tv: Boolean(rules.ignore_year_for_tv),
      skip_available_content: Boolean(rules.skip_available_content),
      skip_unreleased_content: Boolean(rules.skip_unreleased_content),
      use_original_title: Boolean(rules.use_original_title),
      use_alt_titles_original: Boolean(rules.use_alt_titles_original),
      use_alt_titles_language: Boolean(rules.use_alt_titles_language),
      alt_titles_language: rules.alt_titles_language || "all",
      movie_sort_primary: rules.movie_sort_primary || "seeders_desc",
      movie_sort_secondary: rules.movie_sort_secondary || "",
      tv_sort_primary: rules.tv_sort_primary || "seeders_desc",
      tv_sort_secondary: rules.tv_sort_secondary || "",
    },
    target_languages: [],
    exclude_tags: [],
  };
}

type StoredCustomRules = {
  found: boolean;
  value: CustomSearchRules;
};

function customRulesFromStoredValue(
  fallback: CustomSearchRules,
  stored: unknown,
): StoredCustomRules {
  if (!stored || typeof stored !== "object" || Array.isArray(stored)) {
    return { found: false, value: fallback };
  }
  const storedRules = stored as Partial<CustomSearchRules>;
  return {
    found: true,
    value: {
      ...fallback,
      ...storedRules,
      search_rules: { ...fallback.search_rules, ...(storedRules.search_rules || {}) },
      target_languages: arrayValue(storedRules.target_languages),
      exclude_tags: arrayValue(storedRules.exclude_tags),
    },
  };
}

function loadStoredCustomRules(fallback: CustomSearchRules): StoredCustomRules {
  if (typeof window === "undefined") return { found: false, value: fallback };
  try {
    const stored = JSON.parse(window.localStorage.getItem(customRulesStorageKey) || "null") as unknown;
    return customRulesFromStoredValue(fallback, stored);
  } catch {
    return { found: false, value: fallback };
  }
}

function storeCustomRules(value: CustomSearchRules) {
  try {
    window.localStorage.setItem(customRulesStorageKey, JSON.stringify(value));
  } catch {
    // A manual search remains usable when browser storage is unavailable.
  }
}

function csvValues(value: string) {
  return value.split(",").map((item) => item.trim()).filter(Boolean);
}

function csvText(value: string[] | undefined) {
  return (value || []).join(", ");
}

function arrayValue(value: unknown) {
  return Array.isArray(value) ? value.filter((item): item is string => typeof item === "string") : [];
}

function numberValue(value: unknown) {
  return typeof value === "number" && Number.isFinite(value) ? value : 0;
}

export {
  csvText,
  csvValues,
  customRulesFromSearchRules,
  customRulesFromStoredValue,
  loadStoredCustomRules,
  storeCustomRules,
};
