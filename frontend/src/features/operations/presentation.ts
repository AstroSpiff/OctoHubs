import type { Severity } from "@/components/ui/badge";
import type { Operation, OperationStatus, OperationWorkflowStep } from "@/features/operations/types";

const statusLabels: Record<OperationStatus, string> = {
  queued: "In coda",
  running: "In corso",
  success: "Completata",
  error: "Errore",
  skipped: "Saltata",
  interrupted: "Interrotta",
};

const statusSeverities: Record<OperationStatus, Severity> = {
  queued: "neutral",
  running: "info",
  success: "ok",
  error: "error",
  skipped: "neutral",
  interrupted: "warning",
};

export function isActiveOperation(operation: Pick<Operation, "status">) {
  return operation.status === "queued" || operation.status === "running";
}

export function operationStatusLabel(status: OperationStatus) {
  return statusLabels[status] || statusLabels.queued;
}

export function operationStatusSeverity(status: OperationStatus): Severity {
  return statusSeverities[status] || statusSeverities.queued;
}

export function formatOperationTimestamp(value: string) {
  if (!value) return "N/D";
  const timestamp = new Date(value);
  if (Number.isNaN(timestamp.getTime())) return value;
  return new Intl.DateTimeFormat("it-IT", {
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  }).format(timestamp);
}

export function operationCanStop(operation: Operation) {
  return operation.kind === "workflow" && isActiveOperation(operation) && operation.details.can_stop !== false;
}

export function operationWorkflowSteps(operation: Operation): OperationWorkflowStep[] {
  const steps = operation.details.workflow_steps;
  return Array.isArray(steps) ? steps : [];
}

export function operationDetailTags(operation: Operation) {
  const keys = ["current_step_label", "server", "user", "client", "title", "rule_name", "source_username", "target_username", "target_server", "group_name", "target_count", "mode"];
  return keys.flatMap((key) => {
    const value = operation.details[key];
    if (typeof value !== "string" && typeof value !== "number") return [];
    return [{ key, value: String(value) }];
  });
}
