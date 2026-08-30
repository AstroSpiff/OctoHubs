import { normalizeManualSearchMediaType } from "@/features/research/manual-search-query";
import type { CustomSearchRules, ManualSearchHistoryEntry, StreamingSearchInput } from "@/features/research/types";

const supportedIndexers = new Set(["prowlarr", "jackett"]);

function manualSearchInputFromHistory(entry: ManualSearchHistoryEntry): StreamingSearchInput | null {
  const firstItem = entry.items?.[0];
  const context = entry.search_context;
  const query = textValue(context?.query) || textValue(firstItem?.title);
  const indexers = indexerValues(context?.indexers).length
    ? indexerValues(context?.indexers)
    : indexerValues(firstItem?.queries?.map((attempt) => attempt.indexer));
  if (!query || !indexers.length) return null;

  const tmdbId = numberValue(context?.tmdb_id);
  const customRules = objectValue(context?.custom_rules) as CustomSearchRules | undefined;
  return {
    query,
    mediaType: normalizeManualSearchMediaType(context?.media_type || firstItem?.media_type || null),
    indexers,
    ...(tmdbId ? { tmdbId } : {}),
    seasons: numberValues(context?.seasons),
    ...(customRules ? { customRules } : {}),
  };
}

function indexerValues(values: unknown): Array<"prowlarr" | "jackett"> {
  if (!Array.isArray(values)) return [];
  return [...new Set(values.filter((value): value is "prowlarr" | "jackett" => typeof value === "string" && supportedIndexers.has(value)))];
}

function numberValues(values: unknown): number[] {
  if (!Array.isArray(values)) return [];
  return [...new Set(values.filter((value): value is number => typeof value === "number" && Number.isInteger(value) && value >= 0))];
}

function numberValue(value: unknown): number | undefined {
  const number = typeof value === "number" ? value : Number(value);
  return Number.isInteger(number) && number > 0 ? number : undefined;
}

function textValue(value: unknown): string {
  return typeof value === "string" ? value.trim() : "";
}

function objectValue(value: unknown): Record<string, unknown> | undefined {
  return value && typeof value === "object" && !Array.isArray(value) ? value as Record<string, unknown> : undefined;
}

export { manualSearchInputFromHistory };
