import type { Severity } from "@/components/ui/badge";
import type { EventBridgeSaveResult, EventBridgeSettings } from "@/features/event-bridge/types";

type EventBridgeSaveNotice = {
  message: string;
  tone: "success" | "warning";
};

function formatEventBridgeTime(value?: string | null): string {
  if (!value) return "Mai";
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

function eventBridgeSaveNotice(
  result: EventBridgeSaveResult,
): EventBridgeSaveNotice {
  const deliveryFailed = Boolean(
    result.push.error || result.push.http_failed.length,
  );

  return {
    message: result.message || "Configurazione Event Bridge aggiornata.",
    tone: deliveryFailed ? "warning" : "success",
  };
}

function eventBridgeSettingsEqual(left: EventBridgeSettings, right: EventBridgeSettings): boolean {
  const keys = new Set<keyof EventBridgeSettings>([
    ...Object.keys(left),
    ...Object.keys(right),
  ] as Array<keyof EventBridgeSettings>);

  return [...keys].every((key) => {
    const leftValue = left[key];
    const rightValue = right[key];
    if (Array.isArray(leftValue) || Array.isArray(rightValue)) {
      return Array.isArray(leftValue)
        && Array.isArray(rightValue)
        && leftValue.length === rightValue.length
        && leftValue.every((value, index) => value === rightValue[index]);
    }
    return leftValue === rightValue;
  });
}

function eventBridgeSyncSeverity(syncStatus: string): Severity {
  if (syncStatus === "aligned") return "ok";
  if (syncStatus === "mismatch") return "warning";
  return "unknown";
}

export {
  eventBridgeSaveNotice,
  eventBridgeSettingsEqual,
  eventBridgeSyncSeverity,
  formatEventBridgeTime,
};
export type { EventBridgeSaveNotice };
