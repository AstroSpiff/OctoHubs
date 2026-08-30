import { Clock3, RefreshCw, RotateCcw, Trash2 } from "@/components/ui/icons";

import { StatusBadge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { WorkspaceHeading } from "@/components/ui/workspace-heading";
import {
  formatLibraryDate,
  formatLibraryDuration,
  libraryScanProgress,
  libraryScanStatusLabel,
  libraryScanStatusSeverity,
  libraryScanTypeLabel,
} from "@/features/libraries/presentation";
import type { LibraryScanHistoryJob } from "@/features/libraries/types";

type LibraryScanHistoryProps = {
  jobs: LibraryScanHistoryJob[];
  loading: boolean;
  resetting: boolean;
  deletingId?: string;
  onRefresh: () => void;
  onReset: () => void;
  onDelete: (job: LibraryScanHistoryJob) => void;
};

function LibraryScanHistory({
  jobs,
  loading,
  resetting,
  deletingId,
  onRefresh,
  onReset,
  onDelete,
}: LibraryScanHistoryProps) {
  return (
    <section className="library-scan-history" aria-labelledby="library-scan-history-title">
      <WorkspaceHeading
        level="subsection"
        title="Cronologia scansioni"
        titleId="library-scan-history-title"
        description="Operazioni completate o non riuscite registrate da OctoHubs."
        actions={
          <div className="library-scan-history-actions">
            <Button
              type="button"
              variant="ghost"
              size="icon"
              title="Aggiorna cronologia"
              aria-label="Aggiorna cronologia"
              onClick={onRefresh}
              disabled={loading}
            >
              <RefreshCw size={16} className={loading ? "animate-spin" : ""} aria-hidden="true" />
            </Button>
            <Button
              type="button"
              requiresWriteAccess
              variant="ghost"
              size="icon"
              title="Azzera stato scansioni e metadata"
              aria-label="Azzera stato scansioni e metadata"
              onClick={onReset}
              disabled={resetting}
            >
              <RotateCcw size={16} aria-hidden="true" />
            </Button>
          </div>
        }
      />
      {!jobs.length && !loading ? (
        <p className="libraries-empty-line">Nessuna scansione registrata.</p>
      ) : (
        <ul>
          {jobs.slice(0, 20).map((job) => (
            <LibraryScanHistoryItem
              key={job.id}
              job={job}
              deleting={deletingId === job.id}
              onDelete={onDelete}
            />
          ))}
        </ul>
      )}
    </section>
  );
}

function LibraryScanHistoryItem({
  job,
  deleting,
  onDelete,
}: {
  job: LibraryScanHistoryJob;
  deleting: boolean;
  onDelete: (job: LibraryScanHistoryJob) => void;
}) {
  const completedAt = job.completed_at || job.updated_at;
  const libraryCount = job.total_libraries;
  const details = [
    libraryScanTypeLabel(job.scan_type),
    libraryScanStatusLabel(job.status),
    libraryCount === undefined
      ? ""
      : `${libraryCount} ${libraryCount === 1 ? "libreria" : "librerie"}`,
    formatLibraryDuration(job.started_at, completedAt),
  ].filter(Boolean).join(" · ");
  const progress = libraryScanProgress(job.progress);
  const severity = libraryScanStatusSeverity(job.status);

  return (
    <li className={`library-history-item library-history-item--${severity}`}>
      <Clock3 size={15} aria-hidden="true" />
      <div className="library-history-copy">
        <div>
          <strong>{job.group_name || job.server_id || "Libreria"}</strong>
          <StatusBadge severity={severity}>{libraryScanStatusLabel(job.status)}</StatusBadge>
        </div>
        <span>{details}</span>
        {job.message ? <small title={job.message}>{job.message}</small> : null}
        {progress !== undefined ? (
          <div className="library-history-progress" aria-label={`Avanzamento finale ${progress}%`}>
            <i><b style={{ width: `${progress}%` }} /></i>
            <strong>{progress}%</strong>
          </div>
        ) : null}
      </div>
      <time dateTime={completedAt || job.started_at}>
        {formatLibraryDate(completedAt || job.started_at)}
      </time>
      <Button
        type="button"
        requiresWriteAccess
        variant="ghost"
        size="icon"
        className="library-history-delete"
        title="Elimina dalla cronologia"
        aria-label={`Elimina ${job.group_name || "job"} dalla cronologia`}
        onClick={() => onDelete(job)}
        disabled={deleting}
      >
        <Trash2 size={15} className={deleting ? "animate-spin" : ""} aria-hidden="true" />
      </Button>
    </li>
  );
}

export { LibraryScanHistory };
