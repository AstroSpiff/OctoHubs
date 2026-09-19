import { StatusBadge } from "@/components/ui/badge";
import type { Severity } from "@/components/ui/badge";
import type { ProbeComboServerStatusLike } from "@/features/probe/probe-combo-presentation";
import { formatProbeDate } from "@/features/probe/presentation";
import type { ProbeComboTask, ProbeWorkerStatus } from "@/features/probe/types";

type ProbeRecordedRun = {
  serverId: string;
  serverName: string;
  run: NonNullable<ProbeWorkerStatus["last_run"]>;
};

function probeLastRunsForServers(
  serverStatuses: ProbeComboServerStatusLike[],
): ProbeRecordedRun[] {
  return serverStatuses.flatMap(
    ({ serverId, serverName, libraryNames, status }) =>
      status?.last_run
        ? [{
            serverId,
            serverName,
            run: {
              ...status.last_run,
              tasks: status.last_run.tasks?.map((task) => ({
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
  );
}

function ProbeLastRuns({
  serverStatuses,
}: {
  serverStatuses: ProbeComboServerStatusLike[];
}) {
  const runs = probeLastRunsForServers(serverStatuses);

  return (
    <section
      className="probe-combo-last-runs"
      aria-label="Ultime attività Media Probe"
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

export { ProbeLastRuns };
