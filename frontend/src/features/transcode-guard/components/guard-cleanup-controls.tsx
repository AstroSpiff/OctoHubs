import { useState } from "react";

import { Button } from "@/components/ui/button";
import { useConfirmationDialog } from "@/components/ui/use-confirmation-dialog";

function GuardCleanupControls({
  label,
  busy,
  error,
  deleted,
  onCleanup,
}: {
  label: string;
  busy: boolean;
  error?: Error | null;
  deleted?: number;
  onCleanup: (before?: string) => void;
}) {
  const confirmation = useConfirmationDialog();
  const [before, setBefore] = useState("");

  async function clearBefore() {
    if (!before) return;
    if (!await confirmation.confirm({ title: "Pulisci storico", description: `Vuoi rimuovere lo storico ${label.toLocaleLowerCase("it")} precedente al ${formatGuardDate(before)}?`, confirmLabel: "Pulisci storico", tone: "danger" })) return;
    onCleanup(before);
  }

  async function clearAll() {
    if (!await confirmation.confirm({ title: "Azzera storico", description: `Vuoi cancellare tutto lo storico ${label.toLocaleLowerCase("it")} ?`, confirmLabel: "Azzera storico", tone: "danger" })) return;
    onCleanup();
  }

  return (
    <div className="guard-cleanup-panel">
      <div className="guard-cleanup-controls">
        <label>
          <span>Prima del</span>
          <input type="date" value={before} onChange={(event) => setBefore(event.target.value)} disabled={busy} />
        </label>
        <Button type="button" requiresWriteAccess size="compact" variant="ghost" onClick={clearBefore} disabled={!before || busy}>{busy ? "Pulizia..." : "Pulisci vecchi"}</Button>
        <Button type="button" requiresWriteAccess size="compact" variant="danger" onClick={() => void clearAll()} disabled={busy}>Azzera storico</Button>
      </div>
      {error ? <p className="guard-action-feedback guard-action-feedback--error" role="alert">{error.message}</p> : null}
      {deleted !== undefined && !error ? <p className="guard-action-feedback" role="status">{deleted} {label} rimossi.</p> : null}
      {confirmation.dialog}
    </div>
  );
}

function formatGuardDate(value: string) {
  const [year, month, day] = value.split("-");
  return year && month && day ? `${day}/${month}/${year}` : value;
}

export { GuardCleanupControls };
