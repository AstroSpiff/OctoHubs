import type { ScanSummaryItem, ScanTarget } from "@/features/research/types";

function scanSummaryItemKey(item: ScanSummaryItem): string {
  return `${item.request_id}:${item.season ?? "all"}`;
}

function scanTargetForItem(item: ScanSummaryItem): ScanTarget {
  return {
    request_id: item.request_id,
    seasons: typeof item.season === "number" ? [item.season] : null,
    force: false,
  };
}

/**
 * The scan endpoint expects one target per request. A request-level row wins
 * over individual seasons, mirroring the original overview selection model.
 */
function scanTargetsFromItems(
  items: Iterable<ScanSummaryItem>,
): ScanTarget[] {
  const targets = new Map<string, ScanTarget>();

  for (const item of items) {
    const key = String(item.request_id);
    const current = targets.get(key);
    if (item.season === null || item.season === undefined) {
      targets.set(key, { request_id: item.request_id, seasons: null, force: false });
      continue;
    }
    if (current?.seasons === null) continue;
    const seasons = new Set([...(current?.seasons || []), item.season]);
    targets.set(key, {
      request_id: item.request_id,
      seasons: [...seasons].sort((left, right) => left - right),
      force: false,
    });
  }

  return [...targets.values()];
}

export { scanSummaryItemKey, scanTargetForItem, scanTargetsFromItems };
