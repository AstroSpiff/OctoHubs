import { History } from "@/components/ui/icons";
import { useMemo, useState } from "react";

import { StatusBadge } from "@/components/ui/badge";
import type { Severity } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { comboTasksForServers } from "@/features/probe/probe-combo-presentation";
import { formatProbeDate, probeProgress } from "@/features/probe/presentation";
import { ProbeWorkerCard } from "@/features/probe/components/probe-worker-card";
import type { WorkerAction } from "@/features/probe/components/probe-worker-card";
import type {
  ProbeComboTask,
  ProbeScope,
  ProbeWorkerStatus,
} from "@/features/probe/types";

type ProbeComboServerStatus = {
  serverId: string;
  serverName: string;
  status?: ProbeWorkerStatus;
};

type ProbeComboCardProps = {
  scope: ProbeScope;
  status?: ProbeWorkerStatus;
  serverStatuses: ProbeComboServerStatus[];
  actions: WorkerAction[];
};

function ProbeComboCard({
  scope,
  status,
  serverStatuses,
  actions,
}: ProbeComboCardProps) {
  const [showLastRun, setShowLastRun] = useState(false);
  const tasks = useMemo(
    () => comboTasksForServers(scope, serverStatuses),
    [scope, serverStatuses],
  );
  const lastRuns = useMemo(
    () =>
      serverStatuses.flatMap(
        ({ serverId, serverName, status: serverStatus }) =>
          serverStatus?.last_run
            ? [{ serverId, serverName, run: serverStatus.last_run }]
            : [],
      ),
    [serverStatuses],
  );
  const scopeLabel = scope === "recent" ? "ultimi aggiunti" : "librerie";

  return (
    <ProbeWorkerCard
      className="probe-combo-card"
      title="Individuazione + analisi"
      description={`Workflow completo per ${scopeLabel}, con avanzamento distinto per ogni fase.`}
      status={status}
      progress={probeProgress(status)}
      headerActions={
        <Button
          type="button"
          variant="ghost"
          size="compact"
          onClick={() => setShowLastRun((current) => !current)}
          disabled={!lastRuns.length}
          aria-expanded={showLastRun}
        >
          <History size={14} aria-hidden="true" />
          Ultimo run
        </Button>
      }
      actions={actions}
    >
      <ProbeComboBoard tasks={tasks} serverStatuses={serverStatuses} />
      {showLastRun ? <ProbeComboLastRuns runs={lastRuns} /> : null}
    </ProbeWorkerCard>
  );
}

function ProbeComboBoard({
  tasks,
  serverStatuses,
}: {
  tasks: ProbeComboTask[];
  serverStatuses: ProbeComboServerStatus[];
}) {
  const columns = ["todo", "running", "done"] as const;
  const labels = {
    todo: "Da fare",
    running: "In esecuzione",
    done: "Completato",
  };

  return (
    <section
      className="probe-combo-board"
      aria-label="Stato del workflow combinato"
    >
      {columns.map((column) => {
        const entries = tasks.filter(
          (task) => comboTaskState(task, serverStatuses) === column,
        );
        return (
          <div key={column} className="probe-combo-column">
            <header>
              <span>{labels[column]}</span>
              <strong>{entries.length}</strong>
            </header>
            <div>
              {entries.length ? (
                entries.map((task, index) => (
                  <ProbeComboTaskCard
                    key={
                      task.id ||
                      `${task.server_id}:${task.type}:${task.library_id || index}`
                    }
                    task={task}
                    serverStatuses={serverStatuses}
                  />
                ))
              ) : (
                <p>Nessun elemento</p>
              )}
            </div>
          </div>
        );
      })}
    </section>
  );
}

function ProbeComboTaskCard({
  task,
  serverStatuses,
}: {
  task: ProbeComboTask;
  serverStatuses: ProbeComboServerStatus[];
}) {
  const status = serverStatuses.find(
    (entry) => entry.serverId === task.server_id,
  )?.status;
  const progress =
    task.type === "processing" ? probeProgress(status) : undefined;
  const serverName =
    task.server_name ||
    serverStatuses.find((entry) => entry.serverId === task.server_id)
      ?.serverName ||
    "Server";
  const phaseLabel = task.type === "processing" ? "Analisi" : "Individuazione";
  const progressPercent = progress?.total
    ? Math.round((progress.completed / progress.total) * 100)
    : 0;

  return (
    <article className="probe-combo-task">
      <strong>{phaseLabel}</strong>
      <span>{[serverName, task.library_name].filter(Boolean).join(" · ")}</span>
      {progress ? (
        <>
          <small>
            {progress.completed}/{progress.total} · {progressPercent}%
          </small>
          <i>
            <b style={{ width: `${progressPercent}%` }} />
          </i>
        </>
      ) : null}
      {status?.current_item ? <small>{status.current_item}</small> : null}
    </article>
  );
}

function ProbeComboLastRuns({
  runs,
}: {
  runs: Array<{
    serverId: string;
    serverName: string;
    run: NonNullable<ProbeWorkerStatus["last_run"]>;
  }>;
}) {
  return (
    <section
      className="probe-combo-last-runs"
      aria-label="Ultimo run del workflow combinato"
    >
      <header>
        <strong>Ultimo run</strong>
        <span>
          {runs.length === 1 ? runs[0].serverName : `${runs.length} server`}
        </span>
      </header>
      <div>
        {runs.map(({ serverId, serverName, run }) => (
          <article key={serverId}>
            <header>
              <div>
                <strong>{serverName}</strong>
                <time dateTime={run.finished_at}>
                  {formatProbeDate(run.finished_at)}
                </time>
              </div>
              <StatusBadge
                severity={run.status === "interrupted" ? "warning" : "ok"}
              >
                {run.status === "interrupted" ? "Interrotto" : "Completato"}
              </StatusBadge>
            </header>
            {run.tasks?.length ? (
              <ul>
                {run.tasks.map((task, index) => (
                  <li
                    key={
                      task.id ||
                      `${task.server_id}:${task.type}:${task.library_id || index}`
                    }
                  >
                    <span>
                      {task.type === "processing"
                        ? "Analisi"
                        : "Individuazione"}
                    </span>
                    <StatusBadge severity={lastRunSeverity(task.result)}>
                      {lastRunLabel(task.result)}
                    </StatusBadge>
                    <small>
                      {task.note ||
                        task.library_name ||
                        task.server_name ||
                        "Nessun dettaglio"}
                    </small>
                  </li>
                ))}
              </ul>
            ) : (
              <p>Nessun dettaglio registrato.</p>
            )}
          </article>
        ))}
      </div>
    </section>
  );
}

function comboTaskState(
  task: ProbeComboTask,
  statuses: ProbeComboServerStatus[],
): "todo" | "running" | "done" {
  const status = statuses.find(
    (entry) => entry.serverId === task.server_id,
  )?.status;
  if (!status?.running) return "todo";
  if (status.phase === task.type) return "running";
  if (status.phase === "processing" && task.type === "discovery") return "done";
  return "todo";
}

function lastRunSeverity(result?: string): Severity {
  if (result === "error") return "error";
  if (result === "warning") return "warning";
  if (result === "skipped") return "neutral";
  return "ok";
}

function lastRunLabel(result?: string): string {
  if (result === "error") return "Errore";
  if (result === "warning") return "Attenzione";
  if (result === "skipped") return "Non necessario";
  return "Completato";
}

export { ProbeComboCard };
export type { ProbeComboServerStatus };
