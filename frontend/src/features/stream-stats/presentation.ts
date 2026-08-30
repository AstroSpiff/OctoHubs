import type { Severity } from "@/components/ui/badge";
import {
  streamOutcomePresentation,
} from "@/features/streaming/stream-outcome-presentation";
import { streamHistorySignalLabels } from "@/features/streaming/stream-event-presentation";
import type { StreamStatsHistory, StreamStatsTrendItem, StreamStatsUser } from "@/features/stream-stats/types";

export const defaultStatsFilters = { period: "7d", server_id: "", user: "", client: "", issues_only: true, sort: "issues_desc", limit: 160 } as const;

export function formatStatsTime(value: string) {
  const date = new Date(value);
  return value && !Number.isNaN(date.getTime()) ? new Intl.DateTimeFormat("it-IT", { dateStyle: "medium", timeStyle: "medium" }).format(date) : "Mai";
}

export function formatStatsDuration(value: number | null | undefined) {
  if (typeof value !== "number" || !Number.isFinite(value) || value < 0) return "Non disponibile";
  const totalSeconds = Math.round(value);
  const hours = Math.floor(totalSeconds / 3600);
  const minutes = Math.floor((totalSeconds % 3600) / 60);
  const seconds = totalSeconds % 60;
  if (hours) return `${hours} h ${minutes} min`;
  if (minutes) return `${minutes} min ${seconds} sec`;
  return `${seconds} sec`;
}

export function outcomePresentation(outcome: string): { label: string; severity: Severity } {
  return streamOutcomePresentation(outcome);
}

export function userSummaryPresentation(user: Pick<StreamStatsUser, "active" | "correct" | "exits" | "issue_streams" | "resolution_changes">): { label: string; severity: "ok" | "warning" | "error" | "info" | "neutral" } {
  if (user.issue_streams > 0) return { label: "Problemi rilevati", severity: "error" };
  if (user.active > 0) return { label: "Riproduzione in corso", severity: "info" };
  if (user.resolution_changes > 0) return { label: "Cambi di risoluzione", severity: "warning" };
  if (user.correct > 0) return { label: "Riproduzioni corrette", severity: "ok" };
  if (user.exits > 0) return { label: "Uscite senza criticità", severity: "neutral" };
  return { label: "Riproduzioni osservate", severity: "neutral" };
}

function outcomeTone(outcome: string): "ok" | "warning" | "error" | "info" | "neutral" {
  const severity = outcomePresentation(outcome).severity;
  if (severity === "ok" || severity === "warning" || severity === "error") return severity;
  return "neutral";
}

function trendItemDescription(item: StreamStatsTrendItem): string {
  return [
    formatStatsTime(item.at),
    item.title,
    item.server,
    item.client,
    item.device,
    item.quality,
    item.label || outcomePresentation(item.status).label,
  ].filter(Boolean).join(" · ");
}

function streamHistorySignals(stream: StreamStatsHistory): string[] {
  return streamHistorySignalLabels({
    violations: stream.violations_committed,
    actions: stream.action_records?.length ? stream.action_records : stream.actions,
  });
}

export { outcomeTone, streamHistorySignals, trendItemDescription };
