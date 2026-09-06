import {
  ChevronDown,
  FileSearch,
  RefreshCw,
  Rocket,
  Server,
} from "@/components/ui/icons";
import { useEffect, useId, useState } from "react";

import { StatusBadge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { EmbyServerIcon } from "@/features/emby-live/components/emby-server-icon";
import {
  formatLibraryDate,
  libraryEntryScanActivity,
  libraryGroupScanActivity,
  latestLibraryGroupHistory,
  libraryScanStatusLabel,
  libraryScanTypeLabel,
  libraryTypeLabel,
} from "@/features/libraries/presentation";
import type {
  LibraryEntry,
  LibraryGroup,
  LibraryScanHistoryJob,
  ScanJob,
} from "@/features/libraries/types";

type ScanType = "content" | "metadata";

type LibraryGroupCardProps = {
  group: LibraryGroup;
  workflowMode: boolean;
  scanning: boolean;
  scanJobs: ScanJob[];
  scanHistory: LibraryScanHistoryJob[];
  scanningLibraryKeys?: ReadonlySet<string>;
  libraryScanBusy: boolean;
  onScan: (scanType: ScanType) => void;
  onScanLibrary: (library: LibraryEntry, scanType: ScanType) => void;
};

function LibraryGroupCard({
  group,
  workflowMode,
  scanning,
  scanJobs,
  scanHistory,
  scanningLibraryKeys = new Set(),
  libraryScanBusy,
  onScan,
  onScanLibrary,
}: LibraryGroupCardProps) {
  const detailsId = useId();
  const [expanded, setExpanded] = useState(() =>
    Boolean(scanning || libraryGroupScanActivity(group, scanJobs)),
  );
  const serverNames = [
    ...new Set(
      group.libraries.map(
        (library) =>
          library.server_alias || library.server_name || library.server_id,
      ),
    ),
  ];
  const groupActivity = libraryGroupScanActivity(group, scanJobs);
  const latestHistory = latestLibraryGroupHistory(group, scanHistory);
  const groupBusy = scanning || Boolean(groupActivity);
  const groupStatus = scanning
    ? "Avvio in corso"
    : groupActivity
      ? `${libraryScanStatusLabel(groupActivity.status)} ${groupActivity.progress}%`
      : libraryTypeLabel(group.collection_type);

  useEffect(() => {
    if (groupBusy) setExpanded(true);
  }, [groupBusy]);

  return (
    <article className="library-group-card">
      <div className="library-group-heading">
        <h4>
          <button
            type="button"
            className="library-group-disclosure"
            aria-expanded={expanded}
            aria-controls={detailsId}
            onClick={() => setExpanded((current) => !current)}
          >
            <span>
              {group.group_name || "Gruppo senza nome"}
              <ChevronDown
                size={16}
                className={expanded ? "is-expanded" : undefined}
                aria-hidden="true"
              />
            </span>
            <small>
              <Server size={14} aria-hidden="true" />
              {serverNames.join(" · ")}
            </small>
          </button>
        </h4>
        <StatusBadge severity={scanning || groupActivity ? "info" : "neutral"}>
          {groupStatus}
        </StatusBadge>
      </div>
      {groupActivity ? (
        <div
          className="library-group-scan-progress"
          role="progressbar"
          aria-label={`Avanzamento ${group.group_name}`}
          aria-valuemin={0}
          aria-valuemax={100}
          aria-valuenow={groupActivity.progress}
        >
          <span className="library-group-scan-track">
            <span style={{ width: `${groupActivity.progress}%` }} />
          </span>
          <small>
            {groupActivity.jobCount === 1
              ? "1 operazione"
              : `${groupActivity.jobCount} operazioni`}
          </small>
        </div>
      ) : null}
      <div className="library-group-actions">
        <Button
          type="button"
          requiresWriteAccess
          variant="secondary"
          size="compact"
          onClick={() => onScan("content")}
          disabled={groupBusy}
        >
          {workflowMode ? (
            <Rocket size={16} aria-hidden="true" />
          ) : (
            <RefreshCw
              size={16}
              className={scanning ? "animate-spin" : ""}
              aria-hidden="true"
            />
          )}
          {workflowMode ? "Workflow" : "Scansione dei file"}
        </Button>
        <Button
          type="button"
          requiresWriteAccess
          variant="secondary"
          size="compact"
          onClick={() => onScan("metadata")}
          disabled={groupBusy}
        >
          <FileSearch size={16} aria-hidden="true" />
          Metadata
        </Button>
      </div>
      {latestHistory ? (
        <p className="library-group-last-activity">
          Ultima attività registrata: {libraryScanTypeLabel(latestHistory.scan_type)} · {libraryScanStatusLabel(latestHistory.status)} · {formatLibraryDate(latestHistory.completed_at || latestHistory.updated_at || latestHistory.started_at)}
        </p>
      ) : null}
      {expanded ? (
        <div className="library-group-details" id={detailsId}>
        <ul>
          {group.libraries.map((library) => {
            const libraryKey = `${library.server_id}:${library.library_id || library.id || ""}`;
            const libraryActivity = libraryEntryScanActivity(library, scanJobs);
            return (
              <li key={libraryKey}>
                <div className="library-group-library-copy">
                  <strong>
                    <EmbyServerIcon
                      icon={library.server_icon}
                      color={library.server_icon_color}
                      iconStyle={library.server_icon_style}
                      size={14}
                    />
                    {library.server_alias ||
                      library.server_name ||
                      library.server_id}
                  </strong>
                  <small>{library.library_name || "Libreria"}</small>
                  {libraryActivity ? (
                    <span className="library-group-library-activity">
                      <small className="library-group-library-status">
                        {`${libraryScanStatusLabel(libraryActivity.status)} ${libraryActivity.progress}%`}
                      </small>
                      <span className="library-group-library-progress">
                        <span style={{ width: `${libraryActivity.progress}%` }} />
                      </span>
                    </span>
                  ) : null}
                </div>
                <div className="library-group-library-actions">
                  <Button
                    type="button"
                    requiresWriteAccess
                    variant="secondary"
                    size="compact"
                    title="Scansiona file della libreria"
                    aria-label={`Scansiona file di ${library.library_name || "libreria"}`}
                    onClick={() => onScanLibrary(library, "content")}
                    disabled={groupBusy || Boolean(libraryActivity) || libraryScanBusy}
                  >
                    {workflowMode ? (
                      <Rocket size={14} aria-hidden="true" />
                    ) : (
                      <RefreshCw
                        size={14}
                        className={
                          scanningLibraryKeys.has(libraryKey)
                            ? "animate-spin"
                            : ""
                        }
                        aria-hidden="true"
                      />
                    )}
                    {workflowMode ? "Workflow" : "Scansione file"}
                  </Button>
                  <Button
                    type="button"
                    requiresWriteAccess
                    variant="secondary"
                    size="compact"
                    title="Aggiorna metadata della libreria"
                    aria-label={`Aggiorna metadata di ${library.library_name || "libreria"}`}
                    onClick={() => onScanLibrary(library, "metadata")}
                    disabled={groupBusy || Boolean(libraryActivity) || libraryScanBusy}
                  >
                    <FileSearch size={14} aria-hidden="true" />
                    Metadata
                  </Button>
                </div>
              </li>
            );
          })}
        </ul>
        </div>
      ) : null}
    </article>
  );
}

export { LibraryGroupCard };
