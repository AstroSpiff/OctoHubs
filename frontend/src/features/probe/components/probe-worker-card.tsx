import { CircleStop, Gauge, Play, Zap } from "@/components/ui/icons";
import type { ReactNode } from "react";

import { StatusBadge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { probeStatusLabel } from "@/features/probe/presentation";
import type { ProbeWorkerStatus } from "@/features/probe/types";

type WorkerAction = {
  label: string;
  icon: "play" | "zap" | "stop";
  onClick: () => void;
  variant?: "primary" | "secondary" | "ghost";
  disabled?: boolean;
  title?: string;
};

type ProbeWorkerCardProps = {
  className?: string;
  title: string;
  description: string;
  status?: ProbeWorkerStatus;
  headerDivider?: boolean;
  stats?: Array<{ label: string; value: number | string }>;
  children?: ReactNode;
  headerActions?: ReactNode;
  progress?: { completed: number; total: number };
  actions: WorkerAction[];
  canMutate?: boolean;
};

function ProbeWorkerCard({
  className = "",
  title,
  description,
  status,
  headerDivider = false,
  stats,
  children,
  headerActions,
  progress,
  actions,
  canMutate = true,
}: ProbeWorkerCardProps) {
  const running = Boolean(status?.running);
  const progressPercent = progress?.total
    ? Math.round((progress.completed / progress.total) * 100)
    : 0;
  const currentLog = running
    ? status?.last_log || "Preparazione in corso..."
    : "Pronto per l'avvio.";

  return (
    <article
      className={`probe-worker-card ${headerDivider ? "has-header-divider" : ""} ${running ? "is-running" : ""} ${className}`.trim()}
    >
      <header>
        <div className="probe-worker-title-row">
          <h3>{title}</h3>
          <div className="probe-worker-heading-actions">
            {headerActions}
            <StatusBadge
              severity={running ? "info" : "neutral"}
              title={running ? "Worker in esecuzione" : "Nessun worker in esecuzione"}
              aria-live="polite"
            >
              {probeStatusLabel(status)}
            </StatusBadge>
          </div>
        </div>
        <p>{description}</p>
      </header>
      {children}
      {stats?.length ? (
        <dl className="probe-worker-stats">
          {stats.map((stat) => (
            <div key={stat.label}>
              <dt>{stat.label}</dt>
              <dd>{stat.value}</dd>
            </div>
          ))}
        </dl>
      ) : null}
      {progress ? (
        <div
          className="probe-worker-progress"
          aria-label={`Avanzamento ${progressPercent}%`}
        >
          <div>
            <span>Avanzamento</span>
            <strong>
              {progress.completed}/{progress.total}
            </strong>
          </div>
          <i>
            <b style={{ width: `${progressPercent}%` }} />
          </i>
        </div>
      ) : null}
      <p className="probe-worker-log">
        <Gauge size={15} aria-hidden="true" />
        {currentLog}
      </p>
      {canMutate ? <footer>
        {actions.map((action) => (
          <Button
            key={action.label}
            type="button"
            variant={action.variant || "secondary"}
            size="compact"
            onClick={action.onClick}
            disabled={action.disabled}
            title={action.title}
          >
            {action.icon === "play" ? (
              <Play size={14} aria-hidden="true" />
            ) : action.icon === "zap" ? (
              <Zap size={14} aria-hidden="true" />
            ) : (
              <CircleStop size={14} aria-hidden="true" />
            )}
            {action.label}
          </Button>
        ))}
      </footer> : null}
    </article>
  );
}

export { ProbeWorkerCard };
export type { WorkerAction };
