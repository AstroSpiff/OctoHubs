import type { RequestRefreshStatus } from "@/features/configuration/types";
import type { Severity } from "@/components/ui/badge";

type AutomationRefreshPresentation = {
  label: string;
  detail: string;
  occurredAt: string;
  severity: Severity;
};

function requestRefreshPresentation(status?: RequestRefreshStatus): AutomationRefreshPresentation {
  if (!status) return { label: "Mai eseguito", detail: "Nessun aggiornamento richieste registrato.", occurredAt: "", severity: "neutral" };
  if (status.running || status.last_status === "running") return { label: "In aggiornamento", detail: "Aggiornamento richieste in corso.", occurredAt: "", severity: "info" };
  if (status.last_status === "success") return { label: "Completato", detail: "Ultimo aggiornamento richieste completato correttamente.", occurredAt: formatConfigurationMoment(status.completed_at), severity: "ok" };
  if (status.last_status === "skipped") return { label: "Saltato", detail: status.last_warning || "L'ultimo aggiornamento richieste è stato saltato.", occurredAt: formatConfigurationMoment(status.last_warning_at || status.completed_at), severity: status.last_warning ? "warning" : "neutral" };
  if (status.last_status === "error") return { label: "Errore", detail: status.last_error || "L'ultimo aggiornamento richieste non è riuscito.", occurredAt: formatConfigurationMoment(status.completed_at), severity: "error" };
  return { label: "Mai eseguito", detail: "Nessun aggiornamento richieste registrato.", occurredAt: "", severity: "neutral" };
}

function formatConfigurationMoment(value?: string | null): string {
  if (!value) return "";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat("it-IT", {
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  }).format(date);
}

export { formatConfigurationMoment, requestRefreshPresentation };
export type { AutomationRefreshPresentation };
