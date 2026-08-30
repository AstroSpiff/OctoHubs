import type { Severity } from "@/components/ui/badge";
import {
  streamOutcomePresentation,
} from "@/features/streaming/stream-outcome-presentation";
import { streamEventKey, streamEventLabel } from "@/features/streaming/stream-event-presentation";
import type { StreamOutcome } from "@/features/streaming/stream-outcome-presentation";
import type { GuardRecord } from "@/features/transcode-guard/types";

type GuardStreamOutcome = StreamOutcome;

const problemActions = new Set([
  "warn",
  "warning_error",
  "stop",
  "partial_resolved",
  "relapse",
]);

export function recordText(record: GuardRecord, key: string, fallback = "Non disponibile") {
  const value = record[key];
  return typeof value === "string" || typeof value === "number" ? String(value) : fallback;
}

export function recordList(record: GuardRecord, key: string) {
  const value = record[key];
  return Array.isArray(value) ? value.map(String).filter(Boolean) : [];
}

export function recordActions(record: GuardRecord) {
  const actions = record.actions;
  return Array.isArray(actions)
    ? actions.filter((value): value is GuardRecord => Boolean(value) && typeof value === "object" && !Array.isArray(value))
    : [];
}

function actionKey(action: GuardRecord) {
  return streamEventKey(action);
}

function isPlayerAction(action: GuardRecord) {
  return streamEventLabel({ ...action, action: "pause" }) === "Pausa dal player";
}

function actionLabel(action: GuardRecord) {
  return streamEventLabel(action);
}

export function formatGuardTime(value: unknown) {
  if ((typeof value !== "string" && typeof value !== "number") || !value) return "Mai";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat("it-IT", { dateStyle: "medium", timeStyle: "medium" }).format(date);
}

export function isProblemStream(record: GuardRecord) {
  if (recordList(record, "violations_committed").length) return true;
  return recordActions(record).some((action) => problemActions.has(actionKey(action)));
}

export function isPlainCorrectStream(record: GuardRecord) {
  return streamPresentation(record).label === "Corretto";
}

export function streamOutcome(record: GuardRecord): GuardStreamOutcome {
  const actions = recordActions(record).map(actionKey);

  if (actions.includes("stop")) return "stop";
  if (actions.includes("warning_error")) return "error";
  if (actions.includes("relapse")) return "relapse";
  if (actions.includes("partial_resolved")) return "partial";
  if (actions.includes("resolution_change")) return "resolution_change";
  if (actions.includes("resolved") || actions.includes("resolved_later")) {
    return "resolved";
  }
  if (actions.includes("warn")) return "warning";
  if (recordList(record, "violations_committed").length) return "issue";
  if (
    recordList(record, "tags").some(
      (tag) => tag.toLocaleLowerCase("it") === "corretta",
    )
  ) {
    return "correct";
  }
  if (actions.includes("exit")) return "exit";
  return "observed";
}

export function streamPresentation(record: GuardRecord): { label: string; severity: Severity } {
  const lastAction = recordActions(record).at(-1);
  if (
    lastAction &&
    actionKey(lastAction) === "pause" &&
    isPlayerAction(lastAction) &&
    !recordText(record, "ended_at", "")
  ) {
    return { label: "In pausa", severity: "neutral" };
  }

  return streamOutcomePresentation(streamOutcome(record));
}

export function actionSummary(record: GuardRecord) {
  const actions = recordActions(record);
  if (actions.length) return actions.map(actionLabel).join(" · ");
  const fallback = recordText(record, "action", "") || recordText(record, "state", "");
  return fallback ? actionLabel({ ...record, action: fallback }) : "Nessuna azione registrata";
}
