import type { RequestSearchRule, ResearchRequest, ResearchSearchRules } from "@/features/research/types";

type RequestRuleTermField = "query_terms" | "filter_terms" | "exclude_terms";

function rulesFromRequests(requests: ResearchRequest[], globalRules: ResearchSearchRules) {
  return Object.fromEntries(requests.map((request) => [requestKey(request), defaultRequestRule(request, globalRules)]));
}

function defaultRequestRule(request: ResearchRequest, globalRules: ResearchSearchRules): RequestSearchRule {
  const rules = request.rules || {};
  return {
    request_id: request.id ?? request.request_id ?? "",
    enabled: rules.enabled !== false,
    query_terms: termsText(rules.query_terms),
    filter_terms: termsText(rules.filter_terms),
    exclude_terms: termsText(rules.exclude_terms),
    use_original_title: booleanFrom(rules.use_original_title, globalRules.use_original_title),
    use_alt_titles_original: booleanFrom(rules.use_alt_titles_original, globalRules.use_alt_titles_original),
    use_alt_titles_language: booleanFrom(rules.use_alt_titles_language, globalRules.use_alt_titles_language),
    alt_titles_language: stringFrom(rules.alt_titles_language) || globalRules.alt_titles_language || "it",
    year_variance: Math.min(10, Math.max(0, Number(rules.year_variance) || 0)),
  };
}

function appendRequestRuleTerm(rule: RequestSearchRule, field: RequestRuleTermField, term: string) {
  const normalized = term.trim();
  if (!normalized) return rule;
  const terms = rule[field].split(",").map((entry) => entry.trim()).filter(Boolean);
  if (terms.includes(normalized)) return rule;
  return { ...rule, [field]: [...terms, normalized].join(", ") };
}

function requestKey(request: ResearchRequest) {
  return String(request.id ?? request.request_id ?? "unknown");
}

function stringFrom(value: unknown) {
  return typeof value === "string" ? value : "";
}

function termsText(value: unknown) {
  return Array.isArray(value) ? value.filter((item): item is string => typeof item === "string").join(", ") : stringFrom(value);
}

function booleanFrom(value: unknown, fallback: unknown) {
  return typeof value === "boolean" ? value : Boolean(fallback);
}

export { appendRequestRuleTerm, defaultRequestRule, requestKey, rulesFromRequests };
export type { RequestRuleTermField };
