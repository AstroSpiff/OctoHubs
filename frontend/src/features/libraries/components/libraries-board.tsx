import { FolderSearch2 } from "@/components/ui/icons";

import { LibraryGroupCard } from "@/features/libraries/components/library-group-card";
import {
  libraryTypeBucket,
  libraryTypeLabel,
} from "@/features/libraries/presentation";
import type {
  LibraryEntry,
  LibraryGroup,
  LibraryScanHistoryJob,
  ScanJob,
} from "@/features/libraries/types";

const columns = ["movies", "tvshows", "other"] as const;

type LibrariesBoardProps = {
  groups: LibraryGroup[];
  workflowMode: boolean;
  scanningId?: string;
  scanJobs: ScanJob[];
  scanHistory: LibraryScanHistoryJob[];
  scanningLibraryKey?: string;
  libraryScanBusy: boolean;
  onScan: (group: LibraryGroup, scanType: "content" | "metadata") => void;
  onScanLibrary: (
    library: LibraryEntry,
    scanType: "content" | "metadata",
  ) => void;
};

function LibrariesBoard({
  groups,
  workflowMode,
  scanningId,
  scanJobs,
  scanHistory,
  scanningLibraryKey,
  libraryScanBusy,
  onScan,
  onScanLibrary,
}: LibrariesBoardProps) {
  if (!groups.length)
    return (
      <div className="libraries-empty">
        <FolderSearch2 size={24} aria-hidden="true" />
        <div>
          <strong>Nessun gruppo di librerie</strong>
          <p>Verifica la configurazione dei server Emby o modifica i filtri.</p>
        </div>
      </div>
    );

  return (
    <div className="libraries-board">
      {columns.map((column) => {
        const items = groups.filter(
          (group) => libraryTypeBucket(group.collection_type) === column,
        );
        return (
          <section className="libraries-column" key={column}>
            <h3>{libraryTypeLabel(column)}</h3>
            {items.length ? (
              items.map((group) => (
                <LibraryGroupCard
                  key={`${group.collection_type}:${group.group_name}`}
                  group={group}
                  workflowMode={workflowMode}
                  scanning={scanningId === group.group_name}
                  scanJobs={scanJobs}
                  scanHistory={scanHistory}
                  scanningLibraryKey={scanningLibraryKey}
                  libraryScanBusy={libraryScanBusy}
                  onScan={(scanType) => onScan(group, scanType)}
                  onScanLibrary={onScanLibrary}
                />
              ))
            ) : (
              <p className="libraries-column-empty">Nessun gruppo.</p>
            )}
          </section>
        );
      })}
    </div>
  );
}

export { LibrariesBoard };
