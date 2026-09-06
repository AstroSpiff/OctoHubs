import { Database, FileSearch, RefreshCw, Rocket } from "@/components/ui/icons";

import { Button } from "@/components/ui/button";
import { QueryStateBoundary } from "@/components/ui/query-state-boundary";
import { WorkspaceHeading } from "@/components/ui/workspace-heading";
import { EmbyServerIcon } from "@/features/emby-live/components/emby-server-icon";
import { LibraryWorkflowMode } from "@/features/libraries/components/library-workflow-mode";
import type {
  ActiveLibraryScan,
  LibraryActionTarget,
  LibraryMaintenanceAction,
} from "@/features/libraries/types";

type LibraryMaintenanceProps = {
  servers: LibraryActionTarget[];
  serversReady: boolean;
  serversError?: Error | null;
  serversRetrying?: boolean;
  activeScans: ActiveLibraryScan[];
  activeScansReady: boolean;
  activeScansError?: Error | null;
  activeScansRetrying?: boolean;
  busy?: { action: LibraryMaintenanceAction; serverId?: string };
  workflowBusy?: boolean;
  workflowMode: boolean;
  onWorkflowModeChange: (enabled: boolean) => void;
  onRetryServers: () => void;
  onRetryActiveScans: () => void;
  onRun: (action: LibraryMaintenanceAction, serverId?: string) => void;
};

function LibraryMaintenance({
  servers,
  serversReady,
  serversError,
  serversRetrying = false,
  activeScans,
  activeScansReady,
  activeScansError,
  activeScansRetrying = false,
  busy,
  workflowBusy = false,
  workflowMode,
  onWorkflowModeChange,
  onRetryServers,
  onRetryActiveScans,
  onRun,
}: LibraryMaintenanceProps) {
  const isBusy = (action: LibraryMaintenanceAction, serverId?: string) =>
    busy?.action === action && busy.serverId === serverId;
  const actionsDisabled =
    !serversReady || !activeScansReady || Boolean(busy) || workflowBusy;
  const workflowLabel = workflowBusy ? "Workflow in corso..." : "Workflow";

  return (
    <section
      className="libraries-maintenance"
      aria-labelledby="libraries-maintenance-title"
    >
      <WorkspaceHeading
        level="subsection"
        title="Librerie - Tutte"
        titleId="libraries-maintenance-title"
        description="Invia una scansione o un aggiornamento metadata a tutti i server Emby abilitati, oppure agisci su un solo server."
        actions={<LibraryWorkflowMode compact enabled={workflowMode} onChange={onWorkflowModeChange} />}
      />
      <div className="libraries-maintenance-global-actions">
        <Button
          type="button"
          requiresWriteAccess
          variant="primary"
          size="compact"
          onClick={() => onRun("refresh_libraries")}
          disabled={actionsDisabled || !servers.length}
        >
          {workflowMode ? (
            <Rocket size={16} aria-hidden="true" />
          ) : (
            <RefreshCw
              size={16}
              className={isBusy("refresh_libraries") ? "animate-spin" : ""}
              aria-hidden="true"
            />
          )}
          {workflowMode ? workflowLabel : "Scansione dei file"}
        </Button>
        <Button
          type="button"
          requiresWriteAccess
          variant="secondary"
          size="compact"
          onClick={() => onRun("refresh_metadata")}
          disabled={actionsDisabled || !servers.length}
        >
          <FileSearch
            size={16}
            className={isBusy("refresh_metadata") ? "animate-spin" : ""}
            aria-hidden="true"
          />
          Aggiorna metadata
        </Button>
      </div>
      {workflowBusy ? (
        <p className="libraries-maintenance-pending" role="status">
          Un workflow e' gia' in corso. Le nuove operazioni saranno disponibili
          al termine.
        </p>
      ) : null}
      <div className="libraries-maintenance-content">
        <QueryStateBoundary
          error={serversError}
          hasData={serversReady}
          loadingLabel="Caricamento server disponibili..."
          retrying={serversRetrying}
          onRetry={onRetryServers}
        >
          <div className="libraries-server-actions">
            {servers.map((server) => (
              <article key={server.id} className="libraries-server-action">
                <div className="libraries-server-identity">
                  <EmbyServerIcon
                    icon={server.icon}
                    color={server.icon_color}
                    iconStyle={server.icon_style}
                    size={16}
                  />
                  <div>
                    <strong>{server.name}</strong>
                    {server.url ? <small>{server.url}</small> : null}
                  </div>
                </div>
                <div>
                  <Button
                    type="button"
                    requiresWriteAccess
                    variant="secondary"
                    size="compact"
                    onClick={() => onRun("refresh_libraries", server.id)}
                    disabled={actionsDisabled}
                  >
                    {workflowMode ? (
                      <Rocket size={14} aria-hidden="true" />
                    ) : (
                      <RefreshCw
                        size={14}
                        className={
                          isBusy("refresh_libraries", server.id)
                            ? "animate-spin"
                            : ""
                        }
                        aria-hidden="true"
                      />
                    )}
                    {workflowMode ? workflowLabel : "Scansione file"}
                  </Button>
                  <Button
                    type="button"
                    requiresWriteAccess
                    variant="secondary"
                    size="compact"
                    onClick={() => onRun("refresh_metadata", server.id)}
                    disabled={actionsDisabled}
                  >
                    <FileSearch
                      size={14}
                      className={
                        isBusy("refresh_metadata", server.id)
                          ? "animate-spin"
                          : ""
                      }
                      aria-hidden="true"
                    />
                    Metadata
                  </Button>
                </div>
              </article>
            ))}
            {!servers.length ? (
              <p className="libraries-empty-line">
                Nessun server Emby abilitato.
              </p>
            ) : null}
          </div>
        </QueryStateBoundary>
        <QueryStateBoundary
          error={activeScansError}
          hasData={activeScansReady}
          loadingLabel="Caricamento attività Emby..."
          retrying={activeScansRetrying}
          onRetry={onRetryActiveScans}
        >
          <ActiveLibraryScans scans={activeScans} />
        </QueryStateBoundary>
      </div>
    </section>
  );
}

function ActiveLibraryScans({ scans }: { scans: ActiveLibraryScan[] }) {
  return (
    <section
      className="libraries-active-scans"
      aria-labelledby="libraries-active-scans-title"
    >
      <header>
        <Database size={16} aria-hidden="true" />
        <h4 id="libraries-active-scans-title">Attività Emby rilevate</h4>
      </header>
      {!scans.length ? (
        <p>Nessuna scansione Emby in corso.</p>
      ) : (
        <ul>
          {scans.map((scan) => {
            const progress = Math.max(
              0,
              Math.min(100, Math.round((scan.progress || 0) * 100)),
            );
            return (
              <li key={`${scan.server_id}:${scan.task_id || scan.task_name}`}>
                <div>
                  <strong>{scan.server_name || scan.server_id}</strong>
                  <span>{scan.task_name}</span>
                </div>
                <div className="libraries-scan-progress">
                  <span style={{ width: `${progress}%` }} />
                  <small>{progress}%</small>
                </div>
              </li>
            );
          })}
        </ul>
      )}
    </section>
  );
}

export { LibraryMaintenance };
