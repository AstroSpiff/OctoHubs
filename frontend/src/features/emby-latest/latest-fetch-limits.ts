type LatestLimitSettings = {
  max_movies?: number;
  max_series?: number;
};

type LatestFetchLimits = {
  limit: number;
  perServerLimit: number;
};

function latestFetchLimits(
  settings: LatestLimitSettings | undefined,
  serverCount: number | undefined,
): LatestFetchLimits {
  const perServerLimit = Math.max(
    positiveInteger(settings?.max_movies) ?? 100,
    positiveInteger(settings?.max_series) ?? 100,
  );
  const resolvedServerCount = Math.max(1, positiveInteger(serverCount) ?? 1);

  return {
    perServerLimit,
    limit: Math.min(1_000, perServerLimit * resolvedServerCount),
  };
}

function positiveInteger(value: unknown) {
  const resolved = Number(value);
  return Number.isInteger(resolved) && resolved > 0 ? resolved : undefined;
}

export { latestFetchLimits };
export type { LatestFetchLimits };
