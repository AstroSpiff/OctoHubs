import { probeProgress } from "@/features/probe/presentation";
import { ProbeWorkerCard } from "@/features/probe/components/probe-worker-card";
import type { WorkerAction } from "@/features/probe/components/probe-worker-card";
import type { ProbeScope, ProbeWorkerStatus } from "@/features/probe/types";

type ProbeComboCardProps = {
  scope: ProbeScope;
  status?: ProbeWorkerStatus;
  actions: WorkerAction[];
  canMutate?: boolean;
};

function ProbeComboCard({
  scope,
  status,
  actions,
  canMutate = true,
}: ProbeComboCardProps) {
  const scopeLabel = scope === "recent" ? "ultimi aggiunti" : "librerie";

  return (
    <ProbeWorkerCard
      className="probe-combo-card"
      title="Individuazione + analisi"
      description={`Esegue in sequenza individuazione e analisi per ${scopeLabel}.`}
      status={status}
      progress={probeProgress(status)}
      actions={actions}
      canMutate={canMutate}
    />
  );
}

export { ProbeComboCard };
