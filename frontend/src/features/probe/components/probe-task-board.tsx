import { History } from "@/components/ui/icons";
import { useMemo, useState } from "react";

import { StatusBadge } from "@/components/ui/badge";
import type { Severity } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { ProgressFill } from "@/components/ui/progress-fill";
import { ProbeLastRuns } from "@/features/probe/components/probe-last-runs";
import {
  comboTaskOutcome,
  comboTasksForServers,
  comboTaskState,
  currentItemForComboTask,
  currentLibraryForComboTask,
  discoveryMetricsForComboTask,
  progressForComboTask,
} from "@/features/probe/probe-combo-presentation";
import type {
  ProbeComboOutcome,
  ProbeComboServerStatusLike,
} from "@/features/probe/probe-combo-presentation";
import type { ProbeComboTask, ProbeScope } from "@/features/probe/types";

type ProbeTaskBoardProps = {
  scope: ProbeScope;
  serverStatuses: ProbeComboServerStatusLike[];
};

function ProbeTaskBoard({ scope, serverStatuses }: ProbeTaskBoardProps) {
  const [showLastRun, setShowLastRun] = useState(false);
  const tasks = useMemo(
    () => comboTasksForServers(scope, serverStatuses),
    [scope, serverStatuses],
  );
  const hasLastRun = serverStatuses.some((server) => server.status?.last_run);

  return (
    <section
      className="probe-task-board-panel"
      aria-label="Stato condiviso delle attività Media Probe"
    >
      <header>
        <div>
          <h3>Stato attività</h3>
          <p>
            Task avviati dal workflow completo o dai comandi indipendenti.
          </p>
        </div>
        <Button
          type="button"
          variant="ghost"
          size="compact"
          onClick={() => setShowLastRun((current) => !current)}
          disabled={!hasLastRun}
          aria-expanded={showLastRun}
        >
          <History size={14} aria-hidden="true" />
          Ultimo run
        </Button>
      </header>
      <div className="probe-combo-board">
        {(["todo", "running", "terminal"] as const).map((column) => {
          const entries = tasks.filter(
            (task) => comboTaskState(task, serverStatuses) === column,
          );
          return (
            <div key={column} className="probe-combo-column">
              <header>
                <span>{columnLabel(column)}</span>
                <strong>{entries.length}</strong>
              </header>
              <div>
                {entries.length ? (
                  entries.map((task, index) => (
                    <ProbeTaskCard
                      key={
                        task.id ||
                        `${task.server_id}:${task.type}:${task.library_id || index}`
                      }
                      task={task}
                      serverStatuses={serverStatuses}
                      state={column}
                    />
                  ))
                ) : (
                  <p>Nessun elemento</p>
                )}
              </div>
            </div>
          );
        })}
      </div>
      {showLastRun ? (
        <ProbeLastRuns serverStatuses={serverStatuses} />
      ) : null}
    </section>
  );
}

function ProbeTaskCard({
  task,
  serverStatuses,
  state,
}: {
  task: ProbeComboTask;
  serverStatuses: ProbeComboServerStatusLike[];
  state: "todo" | "running" | "terminal";
}) {
  const progress = progressForComboTask(task, serverStatuses);
  const currentItem = currentItemForComboTask(task, serverStatuses);
  const currentLibrary = currentLibraryForComboTask(task, serverStatuses);
  const discoveryMetrics = discoveryMetricsForComboTask(task, serverStatuses);
  const serverName =
    task.server_name ||
    serverStatuses.find((entry) => entry.serverId === task.server_id)
      ?.serverName ||
    "Server";
  const phaseLabel = task.type === "processing" ? "Analisi" : "Individuazione";
  const progressPercent = progress?.total
    ? Math.round((progress.completed / progress.total) * 100)
    : 0;
  const outcome = state === "terminal"
    ? comboTaskOutcome(task, serverStatuses)
    : undefined;

  return (
    <article className={`probe-combo-task is-${outcome || state}`}>
      <header>
        <strong>{phaseLabel}</strong>
        {outcome ? (
          <StatusBadge severity={outcomeSeverity(outcome)}>
            {outcomeLabel(outcome)}
          </StatusBadge>
        ) : null}
      </header>
      <span>{[serverName, currentLibrary].filter(Boolean).join(" · ")}</span>
      {discoveryMetrics ? (
        <small>
          Ispezionati: {discoveryMetrics.scanned} · Individuati: {discoveryMetrics.found}
        </small>
      ) : null}
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

function columnLabel(column: "todo" | "running" | "terminal"): string {
  if (column === "todo") return "Da fare";
  if (column === "running") return "In esecuzione";
  return "Terminato";
}

function outcomeSeverity(outcome: ProbeComboOutcome): Severity {
  if (outcome === "error") return "error";
  if (outcome === "interrupted" || outcome === "partial") return "warning";
  if (outcome === "skipped") return "neutral";
  return "ok";
}

function outcomeLabel(outcome: ProbeComboOutcome): string {
  if (outcome === "error") return "Errore";
  if (outcome === "interrupted") return "Interrotto";
  if (outcome === "partial") return "Parziale";
  if (outcome === "skipped") return "Non necessario";
  return "Completato";
}

export { ProbeTaskBoard };
