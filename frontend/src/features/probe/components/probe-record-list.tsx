import { RotateCcw, Trash2 } from "@/components/ui/icons";

import { StatusBadge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  formatProbeDate,
  probeItemHasIssue,
  probeItemLabel,
} from "@/features/probe/presentation";
import type {
  ProbeBlacklistItem,
  ProbeHistoryItem,
} from "@/features/probe/types";

type RecordKind = "history" | "error" | "incomplete";
type RecordItem = ProbeHistoryItem | ProbeBlacklistItem;

function ProbeRecordList({
  kind,
  items,
  busy,
  onRetry,
  onRemove,
}: {
  kind: RecordKind;
  items: RecordItem[];
  busy: boolean;
  onRetry: (item: RecordItem) => void;
  onRemove?: (item: ProbeBlacklistItem) => void;
}) {
  return (
    <div
      className="probe-record-list"
      role="table"
      tabIndex={0}
      aria-label={recordListLabel(kind)}
    >
      <div className="probe-record-heading" role="row">
        <span role="columnheader">{kind === "history" ? "Data" : "Ultimo tentativo"}</span>
        <span role="columnheader">Titolo</span>
        <span role="columnheader">{kind === "history" ? "Stato" : "Tentativi"}</span>
        <span role="columnheader">
          {kind === "history"
            ? "Dettagli"
            : kind === "error"
              ? "Ultimo errore"
              : "Dettagli"}
        </span>
        <span role="columnheader">Azioni</span>
      </div>
      {items.map((item, index) => (
        <ProbeRecordRow
          key={`${item.item_id}:${item.media_source_id || index}`}
          kind={kind}
          item={item}
          busy={busy}
          onRetry={onRetry}
          onRemove={onRemove}
        />
      ))}
    </div>
  );
}

function ProbeRecordRow({
  kind,
  item,
  busy,
  onRetry,
  onRemove,
}: {
  kind: RecordKind;
  item: RecordItem;
  busy: boolean;
  onRetry: (item: RecordItem) => void;
  onRemove?: (item: ProbeBlacklistItem) => void;
}) {
  const status = item.status?.toLowerCase() || "";
  const date =
    item.processed_at ||
    item.completed_at ||
    item.failed_at ||
    item.updated_at ||
    item.created_at;
  const canRetry = kind !== "history" || probeItemHasIssue(item);

  return (
    <article className="probe-record-row" role="row">
      <time
        className="probe-record-date"
        dateTime={date}
        data-label={kind === "history" ? "Data" : "Ultimo tentativo"}
        role="cell"
      >
        {formatProbeDate(date)}
      </time>
      <strong data-label="Titolo" role="cell">{probeItemLabel(item)}</strong>
      {kind === "history" ? (
        <span className="probe-record-status" data-label="Stato" role="cell">
          <StatusBadge severity={historySeverity(status)}>
            {historyLabel(status)}
          </StatusBadge>
        </span>
      ) : (
        <span className="probe-record-status" data-label="Tentativi" role="cell">
          <span className={`probe-retry-count probe-retry-count--${kind}`}>
            {item.retry_count || 0}
          </span>
        </span>
      )}
      <span
        className="probe-record-detail"
        data-label={
          kind === "history"
            ? "Dettagli"
            : kind === "error"
              ? "Ultimo errore"
              : "Dettagli"
        }
        role="cell"
      >
        {historyDetail(kind, item)}
      </span>
      <span className="probe-record-actions" data-label="Azioni" role="cell">
        {canRetry ? (
          <Button
            type="button"
            requiresWriteAccess
            variant="secondary"
            size="compact"
            onClick={() => onRetry(item)}
            disabled={busy}
          >
            <RotateCcw size={14} aria-hidden="true" />
            Riprova
          </Button>
        ) : null}
        {onRemove ? (
          <Button
            type="button"
            requiresWriteAccess
            variant="ghost"
            size="icon"
            title="Rimuovi dall'elenco"
            aria-label={`Rimuovi ${probeItemLabel(item)} dall'elenco`}
            onClick={() => onRemove(item as ProbeBlacklistItem)}
            disabled={busy}
          >
            <Trash2 size={15} aria-hidden="true" />
          </Button>
        ) : null}
      </span>
    </article>
  );
}

function historySeverity(status: string) {
  if (status === "success") return "ok" as const;
  if (status === "incomplete") return "warning" as const;
  if (status === "error") return "error" as const;
  return "unknown" as const;
}

function recordListLabel(kind: RecordKind) {
  if (kind === "history") return "Storico esecuzioni Media Probe";
  if (kind === "error") return "Errori Media Probe";
  return "Elementi Media Probe incompleti";
}

function historyLabel(status: string) {
  if (status === "success") return "Successo";
  if (status === "incomplete") return "Incompleto";
  if (status === "error") return "Errore";
  return status || "Non disponibile";
}

function historyDetail(kind: RecordKind, item: RecordItem) {
  if (kind === "history") {
    const duration = item.duration_ms
      ? `${(item.duration_ms / 1000).toFixed(2)} s`
      : "";
    return (
      [item.error_details || item.reason, duration]
        .filter(Boolean)
        .join(" · ") || "-"
    );
  }
  return item.reason || item.error_details || "-";
}

export { ProbeRecordList };
