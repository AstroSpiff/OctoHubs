export type DetectedCollectionSource = {
  sourceType: string;
  sourceValue: string;
};

/**
 * Preserve the convenient legacy behavior when an operator pastes a known
 * provider URL into a collection source field.
 */
export function collectionSourceFromValue(
  value: string,
): DetectedCollectionSource | null {
  const traktValue = normalizedTraktListValue(value);
  if (traktValue) {
    return { sourceType: "trakt_list", sourceValue: traktValue };
  }

  const sourceType = detectCollectionSourceType(value);
  return sourceType ? { sourceType, sourceValue: value } : null;
}

export function detectCollectionSourceType(value: string): string {
  const lowered = value.trim().toLocaleLowerCase("en-US");
  if (lowered.includes("mdblist.com/")) return "mdblist";
  if (lowered.includes("trakt.tv/")) return "trakt_list";
  if (lowered.includes("themoviedb.org/list/")) return "tmdb_list";
  if (lowered.includes("themoviedb.org/collection/")) {
    return "tmdb_collection";
  }
  return "";
}

export function hasCollectionSourceInventoryDraft(
  name: string,
  sourceValue: string,
): boolean {
  return Boolean(name.trim() || sourceValue.trim());
}

export function normalizedTraktListValue(value: string): string {
  const trimmed = value.trim();
  if (!trimmed) return "";

  const withoutHash = trimmed.split("#", 1)[0];
  const [baseValue, query = ""] = withoutHash.split("?", 2);
  const querySuffix = query ? `?${query}` : "";
  const directMatch = /^([^/]+)\/([^/]+)$/.exec(baseValue);
  if (directMatch) {
    return `${directMatch[1].toLocaleLowerCase("en-US")}/${directMatch[2]}${querySuffix}`;
  }

  const userMatch = /trakt\.tv\/users\/([^/]+)\/lists\/([^/?#]+)/i.exec(baseValue);
  if (userMatch) {
    return `${userMatch[1].toLocaleLowerCase("en-US")}/${userMatch[2]}${querySuffix}`;
  }

  const listMatch = /trakt\.tv\/lists\/([^/?#]+)/i.exec(baseValue);
  return listMatch ? `${listMatch[1]}${querySuffix}` : "";
}
