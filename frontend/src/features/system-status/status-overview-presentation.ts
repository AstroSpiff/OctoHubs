type OverviewCounts = {
  ok: number;
  warning: number;
  error: number;
  unknown: number;
};

function systemStatusOverviewHeadline(
  counts: OverviewCounts,
  loading: boolean,
) {
  if (loading && !Object.values(counts).some(Boolean)) return "Controllo in corso";
  if (counts.error) return "Attenzione richiesta";
  if (counts.warning) return "Da controllare";
  return "Tutto sotto controllo";
}

export type { OverviewCounts };
export { systemStatusOverviewHeadline };
