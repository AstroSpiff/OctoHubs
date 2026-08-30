const latestDisplayLimitStorageKey = "octohubs_latest_display_limit";
const latestDisplayLimits = [10, 20, 50, 100] as const;
type LatestDisplayStorage = Pick<Storage, "getItem" | "setItem">;

function readLatestDisplayLimit(
  storage: LatestDisplayStorage | null = window.localStorage,
) {
  const stored = Number(storage?.getItem(latestDisplayLimitStorageKey));
  return latestDisplayLimits.includes(stored as (typeof latestDisplayLimits)[number])
    ? stored
    : latestDisplayLimits[0];
}

function saveLatestDisplayLimit(
  limit: number,
  storage: LatestDisplayStorage | null = window.localStorage,
) {
  if (!latestDisplayLimits.includes(limit as (typeof latestDisplayLimits)[number]))
    return;
  storage?.setItem(latestDisplayLimitStorageKey, String(limit));
}

export {
  latestDisplayLimits,
  readLatestDisplayLimit,
  saveLatestDisplayLimit,
};
