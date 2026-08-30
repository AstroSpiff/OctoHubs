import type { ResearchMediaType } from "@/features/research/types";

type ManualSearchQuery = {
  query: string;
  mediaType: ResearchMediaType;
};

function manualSearchFromQuery(search: string): ManualSearchQuery | null {
  const parameters = new URLSearchParams(search);
  const query = parameters.get("independent_query")?.trim() || "";
  if (!query) return null;

  return {
    query,
    mediaType: normalizeManualSearchMediaType(parameters.get("independent_media_type")),
  };
}

function normalizeManualSearchMediaType(value: string | null): ResearchMediaType {
  const normalized = value?.trim().toLocaleLowerCase("en") || "";
  if (["movie", "film"].includes(normalized)) return "movie";
  if (["tv", "series", "serie", "show"].includes(normalized)) return "tv";
  return "unknown";
}

export { manualSearchFromQuery, normalizeManualSearchMediaType };
export type { ManualSearchQuery };
