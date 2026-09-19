import { History } from "@/components/ui/icons";
import { useMemo, useState } from "react";

import { StatusBadge } from "@/components/ui/badge";
import type { Severity } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { ProgressFill } from "@/components/ui/progress-fill";
import {
  comboTasksForServers,
  comboTaskState,
  currentItemForComboTask,
  progressForComboTask,
} from "@/features/probe/probe-combo-presentation";
import type { ProbeComboServerStatusLike } from "@/features/probe/probe-combo-presentation";
import {
  formatProbeDate,
  mergeProbeWorkerStatuses,
  probeProgress,
} from "@/features/probe/presentation";
import { ProbeWorkerCard } from "@/features/probe/components/probe-worker-card";
import type { WorkerAction } from "@/features/probe/components/probe-worker-card";
import type {
  ProbeComboTask,
  ProbeScope,
  ProbeWorkerStatus,
} from "@/features/probe/types";

type ProbeComboServerStatus = ProbeComboServerStatusLike;

type ProbeComboCardProps = {
  scope: ProbeScope;
  status?: ProbeWorkerStatus;
  serverStatuses: ProbeComboServerStatus[];
  actions: WorkerAction[];
  canMutate?: boolean;
};

function ProbeComboCard({
  scope,
  status,
  serverStatuses,
  actions,
  canMutate = true,
}: ProbeComboCardProps) {
  const [showLastRun, setShowLastRun] = useState(false);
  const tasks = useMemo(
    () => comboTasksForServers(scope, serverStatuses),
    [scope, serverStatuses],
  );
  const lastRuns = useMemo(
    () =>
      serverStatuses.flatMap(
        ({ serverId, serverName, libraryNames, status: serverStatus }) =>
          serverStatus?.last_run
            ? [{
                serverId,
                serverName,
                run: {
                  ...serverStatus.last_run,
                  tasks: serverStatus.last_run.tasks?.map((task) => ({
                    ...task,
                    library_name:
                      task.library_name ||
                      (task.library_id
                        ? libraryNames?.[String(task.library_id)]
                        : undefined),
                  })),
                },
              }]
            : [],
      ),
    [serverStatuses],
  );
  const scopeLabel = scope === "recent" ? "ultimi aggiunti" : "librerie";
  const activeStandaloneStatuses = serverStatuses.flatMap((serverStatus) =>
    [serverStatus.discoveryStatus, serverStatus.processingStatus].filter(
      (workerStatus): workerStatus is ProbeWorkerStatus =>
        Boolean(workerStatus?.running),
    ),
  );
  const displayedStatus = status?.running
    ? status
    : mergeProbeWorkerStatuses(activeStandaloneStatuses) || status;

  return (
    <ProbeWorkerCard
      className="probe-combo-card"
      title="Individuazione + analisi"
      description={`Workflow completo per ${scopeLabel}, con avanzamento distinto per ogni fase.`}
      status={displayedStatus}
      progress={probeProgress(displayedStatus)}
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
      canMutate={canMutate}
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
  const progress = progressForComboTask(task, serverStatuses);
  const currentItem = currentItemForComboTask(task, serverStatuses);
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
            <ProgressFill value={progressPercent} />
          </i>
        </>
      ) : null}
      {currentItem ? <small>{currentItem}</small> : null}
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
          {runs.length === 1
            ? `${runs[0].run.tasks?.length || 0} attività`
            : `${runs.length} server`}
        </span>
      </header>
      <div>
        {runs.map(({ serverId, serverName, run }) => (
          <article key={serverId}>
            <header>
              <div>
                <strong>{serverName}</strong>
                <time dateTime={run.finished_at}>
                  Fine: {formatProbeDate(run.finished_at)}
                </time>
                {run.started_at ? (
                  <small>
                    Inizio: {formatProbeDate(run.started_at)} · Durata: {formatRunDuration(
                      run.started_at,
                      run.finished_at,
                    )}
                  </small>
                ) : null}
              </div>
              <StatusBadge severity={lastRunStatusSeverity(run.status)}>
                {lastRunStatusLabel(run.status)}
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
                    <div>
                      <span>
                        {task.type === "processing"
                          ? "Analisi"
                          : "Individuazione"}
                      </span>
                      <strong>
                        {task.library_name ||
                          task.server_name ||
                          "Tutte le librerie"}
                      </strong>
                    </div>
                    <StatusBadge severity={lastRunSeverity(task.result)}>
                      {lastRunLabel(task.result)}
                    </StatusBadge>
                    {lastRunTaskDetail(task) ? (
                      <small>{lastRunTaskDetail(task)}</small>
                    ) : null}
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

function formatRunDuration(startedAt?: string | null, finishedAt?: string): string {
  if (!startedAt || !finishedAt) return "Non disponibile";
  const durationSeconds = Math.max(
    0,
    Math.round((Date.parse(finishedAt) - Date.parse(startedAt)) / 1000),
  );
  if (!Number.isFinite(durationSeconds)) return "Non disponibile";
  const hours = Math.floor(durationSeconds / 3600);
  const minutes = Math.floor((durationSeconds % 3600) / 60);
  const seconds = durationSeconds % 60;
  return [
    hours ? `${hours} h` : "",
    minutes ? `${minutes} min` : "",
    !hours && (!minutes || seconds) ? `${seconds} s` : "",
  ].filter(Boolean).join(" ");
}

function formatRunCount(value: number): string {
  return new Intl.NumberFormat("it-IT").format(value);
}

function formatRunMetric(
  value: number,
  singular: string,
  plural: string,
): string {
  return `${formatRunCount(value)} ${value === 1 ? singular : plural}`;
}

function lastRunTaskDetail(task: ProbeComboTask): string | undefined {
  const details: string[] = [];
  if (task.type === "discovery") {
    if (task.scanned !== undefined) {
      details.push(
        task.total !== undefined
          ? `${formatRunCount(task.scanned)}/${formatRunCount(task.total)} elementi ispezionati`
          : `${formatRunCount(task.scanned)} elementi ispezionati`,
      );
    }
    if (task.found !== undefined) {
      details.push(formatRunMetric(task.found, "file individuato", "file individuati"));
    }
  } else if (task.type === "processing") {
    if (task.processed !== undefined) {
      const total = task.total !== undefined
        ? ` su ${formatRunCount(task.total)}`
        : "";
      details.push(`${formatRunCount(task.processed)} completati${total}`);
    }
    if (task.incomplete) {
      details.push(formatRunMetric(task.incomplete, "incompleto", "incompleti"));
    }
    if (task.errors) {
      details.push(formatRunMetric(task.errors, "errore", "errori"));
    }
  }
  const genericNotes = new Set(["Completato", "Interrotto"]);
  if (task.note && !genericNotes.has(task.note)) details.push(task.note);
  return details.length ? details.join(" · ") : undefined;
}

function lastRunStatusSeverity(status?: string): Severity {
  if (status === "error") return "error";
  if (status === "interrupted" || status === "partial") return "warning";
  return "ok";
}

function lastRunStatusLabel(status?: string): string {
  if (status === "error") return "Errore";
  if (status === "interrupted") return "Interrotto";
  if (status === "partial") return "Parziale";
  return "Completato";
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
