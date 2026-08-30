import type { Severity } from "@/components/ui/badge";

type StreamOutcome =
  | "correct"
  | "error"
  | "exit"
  | "issue"
  | "observed"
  | "partial"
  | "relapse"
  | "resolution_change"
  | "resolved"
  | "stop"
  | "warning";

type StreamOutcomePresentation = {
  label: string;
  severity: Severity;
};

const presentations: Record<StreamOutcome, StreamOutcomePresentation> = {
  correct: { label: "Corretto", severity: "ok" },
  error: { label: "Errore", severity: "error" },
  exit: { label: "Uscito", severity: "neutral" },
  issue: { label: "Problema rilevato", severity: "error" },
  observed: { label: "Osservato", severity: "neutral" },
  partial: { label: "Risolto parzialmente", severity: "warning" },
  relapse: { label: "Ricaduta", severity: "error" },
  resolution_change: { label: "Cambio risoluzione", severity: "warning" },
  resolved: { label: "Risolto", severity: "ok" },
  stop: { label: "Stop del Guard", severity: "error" },
  warning: { label: "Avviso", severity: "warning" },
};

function streamOutcomePresentation(value: string): StreamOutcomePresentation {
  return presentations[value as StreamOutcome] || presentations.observed;
}

export { streamOutcomePresentation };
export type { StreamOutcome, StreamOutcomePresentation };
