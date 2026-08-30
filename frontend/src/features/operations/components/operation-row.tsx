import { AlertTriangle, CheckCircle2, Clock3, LoaderCircle, MinusCircle, PauseCircle } from "@/components/ui/icons";

import { StatusBadge, type Severity } from "@/components/ui/badge";
import {
  formatOperationTimestamp,
  operationStatusLabel,
  operationStatusSeverity,
} from "@/features/operations/presentation";
import type { Operation, OperationStatus } from "@/features/operations/types";

const statusIcons: Record<OperationStatus, typeof Clock3> = {
  queued: Clock3,
  running: LoaderCircle,
  success: CheckCircle2,
  error: AlertTriangle,
  skipped: MinusCircle,
  interrupted: PauseCircle,
};

function detailEntries(operation: Operation) {
  const allowedKeys = ["server", "user", "client", "title", "rule_name"];
  return allowedKeys
    .map((key) => [key, operation.details?.[key]])
    .filter((entry): entry is [string, string | number] => typeof entry[1] === "string" || typeof entry[1] === "number");
}

function OperationRow({ operation }: { operation: Operation }) {
  const status = operation.status in statusIcons ? operation.status : "queued";
  const severity: Severity = operationStatusSeverity(status);
  const Icon = statusIcons[status];
  const progress = Math.max(0, Math.min(100, Number(operation.progress) || 0));
  const details = detailEntries(operation);
  const isActive = operation.status === "queued" || operation.status === "running";

  return (
    <article className="operation-row">
      <div className="operation-row-heading">
        <span className={`operation-status-icon operation-status-icon--${severity}`}>
          <Icon size={18} className={operation.status === "running" ? "animate-spin" : ""} aria-hidden="true" />
        </span>
        <div>
          <h2>{operation.title}</h2>
          <p>{operation.summary || operation.kind}</p>
        </div>
        <StatusBadge severity={severity}>{operationStatusLabel(status)}</StatusBadge>
      </div>
      <p className="operation-message">{operation.error || operation.message || "Nessun dettaglio disponibile"}</p>
      {isActive ? (
        <div className="operation-progress" aria-label={`Avanzamento ${progress}%`}>
          <div><span>Avanzamento</span><strong>{progress}%</strong></div>
          <span className="operation-progress-track"><span style={{ width: `${progress}%` }} /></span>
          {operation.total ? <small>{operation.current} di {operation.total}</small> : null}
        </div>
      ) : null}
      {details.length ? (
        <dl className="operation-details">
          {details.map(([key, value]) => <div key={key}><dt>{key.replace("_", " ")}</dt><dd>{value}</dd></div>)}
        </dl>
      ) : null}
      <time dateTime={operation.updated_at}>Aggiornata {formatOperationTimestamp(operation.updated_at)}</time>
    </article>
  );
}

export { OperationRow };
