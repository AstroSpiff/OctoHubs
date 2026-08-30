import type { SearchResult } from "@/features/research/types";

type ResolutionBucketKey = "2160p" | "1440p" | "1080p" | "720p" | "576p" | "480p" | "other";
type SearchResultEntry = { key: string; result: SearchResult };
type IndexedSearchResult = SearchResultEntry & {
  index: number;
  duplicates: SearchResultEntry[];
};
type SearchResultBucket = { key: ResolutionBucketKey; label: string; items: IndexedSearchResult[] };
type SearchResultSeasonGroup = {
  key: string;
  label: string;
  items: IndexedSearchResult[];
};

const bucketOrder: ResolutionBucketKey[] = ["2160p", "1440p", "1080p", "720p", "576p", "480p", "other"];
const bucketLabels: Record<ResolutionBucketKey, string> = {
  "2160p": "2160p / 4K",
  "1440p": "1440p QHD",
  "1080p": "1080p Full HD",
  "720p": "720p HD",
  "576p": "576p DVD",
  "480p": "480p SD",
  other: "Altre risoluzioni",
};

function groupSearchResultsByResolution(results: SearchResult[]): SearchResultBucket[] {
  return groupIndexedResultsByResolution(indexSearchResults(results));
}

function groupIndexedResultsByResolution(
  items: IndexedSearchResult[],
): SearchResultBucket[] {
  const buckets = new Map<ResolutionBucketKey, IndexedSearchResult[]>();
  bucketOrder.forEach((key) => buckets.set(key, []));
  items.forEach((item) => {
    buckets
      .get(resolutionBucket(item.result.resolution_bucket || item.result.resolution))
      ?.push(item);
  });
  return bucketOrder.flatMap((key) => {
    const items = buckets.get(key) || [];
    return items.length ? [{ key, label: bucketLabels[key], items }] : [];
  });
}

function groupSearchResultsBySeason(
  results: SearchResult[],
): SearchResultSeasonGroup[] {
  const groups = new Map<string, SearchResultSeasonGroup>();
  indexSearchResults(results).forEach((item) => {
    const season = resultSeason(item.result);
    const current = groups.get(season.key);
    if (current) {
      current.items.push(item);
      return;
    }
    groups.set(season.key, { ...season, items: [item] });
  });
  return [...groups.values()].sort(compareSeasonGroups);
}

function filterBucketResults(items: IndexedSearchResult[], query: string) {
  const terms = query.split(",").map((term) => term.trim().toLocaleLowerCase("it-IT")).filter(Boolean);
  if (!terms.length) return items;
  return items.filter(({ result, duplicates }) =>
    [result, ...duplicates.map((duplicate) => duplicate.result)].some((entry) =>
      terms.every((term) => String(entry.title || "").toLocaleLowerCase("it-IT").includes(term)),
    ),
  );
}

function searchResultDuplicates(result: SearchResult): SearchResult[] {
  return Array.isArray(result.duplicates)
    ? result.duplicates.filter((duplicate): duplicate is SearchResult =>
        Boolean(duplicate && typeof duplicate === "object"),
      )
    : [];
}

function indexSearchResults(results: SearchResult[]): IndexedSearchResult[] {
  return results.map((result, index) => {
    const key = String(index);
    return {
      index,
      key,
      result,
      duplicates: searchResultDuplicates(result).map((duplicate, duplicateIndex) => ({
        key: `${key}:duplicate:${duplicateIndex}`,
        result: duplicate,
      })),
    };
  });
}

function searchResultEntries(results: SearchResult[]): SearchResultEntry[] {
  return results.flatMap((result, index) => [
    { key: String(index), result },
    ...searchResultDuplicates(result).map((duplicate, duplicateIndex) => ({
      key: `${index}:duplicate:${duplicateIndex}`,
      result: duplicate,
    })),
  ]);
}

function resultSeason(result: SearchResult): Omit<SearchResultSeasonGroup, "items"> {
  const number = seasonNumber(result);
  if (number === null) {
    return { key: "all", label: "Tutti i risultati" };
  }
  if (number === 0) return { key: "season-0", label: "Speciali" };
  return { key: `season-${number}`, label: `Stagione ${number}` };
}

function seasonNumber(result: SearchResult) {
  const explicit = Number(result.season_number);
  if (Number.isInteger(explicit) && explicit >= 0) return explicit;
  const label = String(result.season_label || result.episode_code || "");
  const match = label.match(/(?:^|\s)(?:stagione|season|s)\s*0*(\d{1,2})(?:\b|e)/i);
  return match ? Number(match[1]) : null;
}

function compareSeasonGroups(
  first: SearchResultSeasonGroup,
  second: SearchResultSeasonGroup,
) {
  if (first.key === "all") return second.key === "all" ? 0 : 1;
  if (second.key === "all") return -1;
  return Number(first.key.slice(7)) - Number(second.key.slice(7));
}

function resolutionBucket(value: unknown): ResolutionBucketKey {
  const normalized = String(value || "").toLowerCase();
  return bucketOrder.includes(normalized as ResolutionBucketKey) ? normalized as ResolutionBucketKey : "other";
}

export {
  filterBucketResults,
  groupIndexedResultsByResolution,
  groupSearchResultsByResolution,
  groupSearchResultsBySeason,
  resolutionBucket,
  searchResultEntries,
};
export type {
  IndexedSearchResult,
  SearchResultBucket,
  SearchResultEntry,
  SearchResultSeasonGroup,
};
