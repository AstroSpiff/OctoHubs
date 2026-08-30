import {
  CircleAlert,
  CircleCheck,
  CircleHelp,
  LoaderCircle,
  TriangleAlert,
} from "@/components/ui/icons";

import { StatusBadge } from "@/components/ui/badge";
import { WorkspaceStatusOverview } from "@/components/ui/workspace-status-overview";
import { formatSystemStatusTime } from "@/features/system-status/presentation";
import {
  systemStatusOverviewHeadline,
  type OverviewCounts,
} from "@/features/system-status/status-overview-presentation";
import type { Severity } from "@/components/ui/badge";

function SystemStatusOverview({
  counts,
  generatedAt,
  loading = false,
}: {
  counts: OverviewCounts;
  generatedAt: string;
  loading?: boolean;
}) {
  const headline = systemStatusOverviewHeadline(counts, loading);
  const severity = overviewSeverity(counts, loading);
  const Icon = overviewIcon(severity);
  const countItems: Array<{
    key: keyof OverviewCounts;
    label: string;
    tone: "error" | "neutral" | "ok" | "warning";
  }> = [
    { key: "error", label: "Errori", tone: "error" },
    { key: "warning", label: "Avvisi", tone: "warning" },
    { key: "unknown", label: "Da verificare", tone: "neutral" },
    { key: "ok", label: "OK", tone: "ok" },
  ];

  return (
    <WorkspaceStatusOverview
      aria-live="polite"
      className="status-overview"
      description={
        generatedAt
          ? `Ultimo aggiornamento ${formatSystemStatusTime(generatedAt)}`
          : "In attesa del primo aggiornamento"
      }
      icon={<Icon className={loading ? "animate-spin" : ""} size={22} aria-hidden="true" />}
      iconTone={severity === "unknown" ? "neutral" : severity}
      metrics={countItems.map(({ key, label, tone }) => ({
        label,
        tone,
        value: counts[key],
      }))}
      status={<StatusBadge severity={severity}>{overviewStatusLabel(severity)}</StatusBadge>}
      title={headline}
    />
  );
}

function overviewSeverity(counts: OverviewCounts, loading: boolean): Severity {
  if (loading && !Object.values(counts).some(Boolean)) return "info";
  if (counts.error) return "error";
  if (counts.warning) return "warning";
  if (counts.unknown) return "unknown";
  return "ok";
}

function overviewStatusLabel(severity: Severity) {
  if (severity === "info") return "Aggiornamento";
  if (severity === "error") return "Attenzione";
  if (severity === "warning" || severity === "unknown") return "Da verificare";
  return "Operativo";
}

function overviewIcon(severity: Severity) {
  if (severity === "info") return LoaderCircle;
  if (severity === "error") return CircleAlert;
  if (severity === "warning") return TriangleAlert;
  if (severity === "unknown") return CircleHelp;
  return CircleCheck;
}

export { SystemStatusOverview };
