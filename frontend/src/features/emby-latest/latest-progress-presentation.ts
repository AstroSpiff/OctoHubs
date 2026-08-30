import type { LatestProgressSnapshot } from "@/features/emby-latest/types";

type LatestRefreshPresentation = {
  label: string;
  message: string;
  completed?: number;
  total?: number;
  percent?: number;
};

function latestRefreshPresentation(
  progress: LatestProgressSnapshot | undefined,
): LatestRefreshPresentation {
  const state = String(progress?.state || "").toLowerCase();
  const total = positiveInteger(progress?.total);
  const completed = nonNegativeInteger(progress?.completed);
  const label =
    state === "collecting"
      ? "Raccolta da Emby"
      : state === "enriching"
        ? "Arricchimento dati"
        : "Aggiornamento pubblicazioni";
  const message = String(progress?.message || "Aggiornamento in corso");
  const percent =
    total !== undefined && completed !== undefined
      ? Math.max(0, Math.min(100, Math.round((completed / total) * 100)))
      : undefined;

  return { label, message, completed, total, percent };
}

function positiveInteger(value: unknown) {
  const resolved = Number(value);
  return Number.isInteger(resolved) && resolved > 0 ? resolved : undefined;
}

function nonNegativeInteger(value: unknown) {
  const resolved = Number(value);
  return Number.isInteger(resolved) && resolved >= 0 ? resolved : undefined;
}

export { latestRefreshPresentation };
export type { LatestRefreshPresentation };
