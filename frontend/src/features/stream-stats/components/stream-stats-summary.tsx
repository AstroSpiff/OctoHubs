import { CircleCheck, CircleX, LogOut, ShieldAlert, Timer, Undo2, Users } from "@/components/ui/icons";
import type { IconComponent } from "@/components/ui/icons";

import { WorkspaceStatusOverview } from "@/components/ui/workspace-status-overview";
import type { StatsSummary } from "@/features/stream-stats/types";

function StreamStatsSummary({ summary }: { summary: StatsSummary }) {
  const metrics: Array<[string, number, IconComponent, "neutral" | "ok" | "warning" | "error" | "info"]> = [
    ["Utenti", summary.users, Users, "neutral"],
    ["Stream", summary.streams, ShieldAlert, "neutral"],
    ["Corrette", summary.correct, CircleCheck, "ok"],
    ["Problemi", summary.issue_streams, CircleX, "error"],
    ["Risolti", summary.resolved, Undo2, "ok"],
    ["Stop", summary.stops, ShieldAlert, "error"],
    ["Uscite", summary.exits, LogOut, "neutral"],
    ["In corso", summary.active, Timer, "info"],
  ];
  return (
    <WorkspaceStatusOverview
      aria-live="polite"
      className="stream-stats-summary"
      description="Le uscite sono conteggiate separatamente e non sono problemi."
      icon={<ShieldAlert size={22} aria-hidden="true" />}
      iconTone={summary.issue_streams ? "warning" : "ok"}
      metrics={metrics.map(([label, value, Icon, tone]) => ({
        label: <><Icon size={13} aria-hidden="true" /> {label}</>,
        tone,
        value,
      }))}
      title={`${summary.problem_rate}% stream con problemi`}
    />
  );
}

export { StreamStatsSummary };
