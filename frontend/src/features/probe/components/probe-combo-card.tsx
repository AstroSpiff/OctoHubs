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
  const description = scope === "recent"
    ? "Individua i file tra gli ultimi aggiunti e analizza in sequenza quelli trovati."
    : "Individua i file nelle librerie selezionate e analizza in sequenza quelli trovati.";

  return (
    <ProbeWorkerCard
      className="probe-combo-card"
      title="Individuazione + analisi"
      description={description}
      status={status}
      progress={probeProgress(status)}
      actions={actions}
      canMutate={canMutate}
    />
  );
}

export { ProbeComboCard };
