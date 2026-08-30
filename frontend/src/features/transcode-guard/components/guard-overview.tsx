import { PauseCircle, ShieldCheck } from "@/components/ui/icons";

import { StatusBadge } from "@/components/ui/badge";
import { WorkspaceStatusOverview } from "@/components/ui/workspace-status-overview";
import { formatGuardTime } from "@/features/transcode-guard/presentation";
import type { GuardRunResult } from "@/features/transcode-guard/types";

function GuardOverview({
  running,
  activeViolations,
  lastResult,
  updatedAt,
}: {
  running: boolean;
  activeViolations: number;
  lastResult: GuardRunResult;
  updatedAt: number;
}) {
  const metrics = [
    { label: "Attive", value: activeViolations },
    { label: "Stream verificati", value: lastResult.checked },
    { label: "Violazioni", value: lastResult.violations },
    { label: "Avvisi", value: lastResult.warned },
    { label: "Stop", value: lastResult.stopped },
  ];
  return (
    <WorkspaceStatusOverview
      aria-live="polite"
      className="guard-overview"
      description={`Stato aggiornato: ${formatGuardTime(updatedAt)}`}
      icon={running ? <ShieldCheck size={22} aria-hidden="true" /> : <PauseCircle size={22} aria-hidden="true" />}
      iconTone={running ? "ok" : "warning"}
      metrics={metrics}
      status={<StatusBadge severity={running ? "ok" : "warning"}>{running ? "Attivo" : "Sospeso"}</StatusBadge>}
      title={running ? "Transcode Guard attivo" : "Transcode Guard sospeso"}
    />
  );
}

export { GuardOverview };
