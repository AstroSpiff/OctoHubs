import { Activity, CheckCircle2, ListChecks } from "@/components/ui/icons";

import { Card } from "@/components/ui/card";
import type { Operation } from "@/features/operations/types";

function OperationsSummary({ operations, activeCount }: { operations: Operation[]; activeCount: number }) {
  const failed = operations.filter((operation) => operation.status === "error").length;
  const completed = operations.filter((operation) => operation.status === "success").length;
  return (
    <Card className="operations-summary" aria-live="polite">
      <div className="operations-summary-primary">
        <span><Activity size={23} aria-hidden="true" /></span>
        <div>
          <strong>{activeCount ? `${activeCount} operazioni in corso` : "Nessuna operazione attiva"}</strong>
          <small>La lista si aggiorna automaticamente mentre sono in corso attivita.</small>
        </div>
      </div>
      <dl className="operations-summary-counts">
        <div><dt><ListChecks size={14} aria-hidden="true" /> Totali</dt><dd>{operations.length}</dd></div>
        <div><dt><CheckCircle2 size={14} aria-hidden="true" /> Completate</dt><dd>{completed}</dd></div>
        <div><dt><Activity size={14} aria-hidden="true" /> Errori</dt><dd>{failed}</dd></div>
      </dl>
    </Card>
  );
}

export { OperationsSummary };
