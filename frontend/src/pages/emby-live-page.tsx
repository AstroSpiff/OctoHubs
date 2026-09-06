import { RefreshCw, RotateCw } from "@/components/ui/icons";

import { Button } from "@/components/ui/button";
import { QueryStateBoundary } from "@/components/ui/query-state-boundary";
import { WorkspaceHeading } from "@/components/ui/workspace-heading";
import { WorkspacePage } from "@/components/ui/workspace-layout";
import { useConfirmationDialog } from "@/components/ui/use-confirmation-dialog";
import { LiveActionResult } from "@/features/emby-live/components/live-action-result";
import { LiveOverview } from "@/features/emby-live/components/live-overview";
import { LiveServerList } from "@/features/emby-live/components/live-server-list";
import { LiveStreamList } from "@/features/emby-live/components/live-stream-list";
import { useEmbyLive } from "@/features/emby-live/use-emby-live";
import { useLiveServerActions } from "@/features/emby-live/use-live-server-actions";

function EmbyLivePage() {
  const live = useEmbyLive();
  const confirmation = useConfirmationDialog();
  const serverActions = useLiveServerActions({
    confirm: confirmation.confirm,
    refreshLive: live.refresh,
    refreshServer: live.refreshServer,
  });
  const servers = Object.values(live.snapshot?.servers || {});
  const restartingAll = serverActions.restart.isPending && !serverActions.restart.variables;
  const restartingServerId = serverActions.restart.isPending
    ? serverActions.restart.variables || null
    : null;

  return (
    <WorkspacePage>
      <WorkspaceHeading
        actionsClassName="emby-live-page-actions"
        level="section"
        title="Emby Live"
        description="Monitoraggio completo dei server, delle attività e delle riproduzioni attive, con i comandi operativi indispensabili nello stesso punto."
        actions={<>
          <Button
            type="button"
            variant="secondary"
            size="compact"
            onClick={live.refresh}
            disabled={live.connection === "loading"}
          >
            <RefreshCw
              size={16}
              className={live.connection === "loading" ? "animate-spin" : ""}
              aria-hidden="true"
            />
            Aggiorna
          </Button>
          <Button
            type="button"
            requiresWriteAccess
            variant="danger"
            size="compact"
            className="emby-live-page-restart-action"
            onClick={() => void serverActions.requestRestart()}
            disabled={!servers.some((server) => server.server.enabled) || serverActions.restart.isPending}
          >
            <RotateCw size={16} className={restartingAll ? "animate-spin" : ""} aria-hidden="true" />
            {restartingAll ? "Riavvio in corso..." : "Riavvia tutti"}
          </Button>
        </>}
      />
      {serverActions.restart.data ? <LiveActionResult result={serverActions.restart.data} /> : null}
      {serverActions.restart.error ? <div className="inline-alert inline-alert--error" role="alert">{serverActions.restart.error.message}</div> : null}
      {serverActions.taskNotice ? <div className="inline-alert inline-alert--success" role="status">{serverActions.taskNotice}</div> : null}
      <QueryStateBoundary
        error={live.error ? new Error(live.error) : null}
        hasData={Boolean(live.snapshot)}
        loadingLabel="Caricamento stato Emby Live..."
        retrying={live.connection === "loading"}
        onRetry={live.refresh}
      >
        <LiveOverview
          servers={servers}
          connection={live.connection}
          updatedAt={live.updatedAt}
        />
        <LiveServerList
          servers={servers}
          controls={{
            refreshingServerIds: serverActions.refreshingServerIds,
            refreshErrors: serverActions.refreshErrors,
            restartingServerId,
            restartDisabled: serverActions.restart.isPending,
            stoppingTaskKeys: serverActions.stoppingTaskKeys,
            taskStopErrors: serverActions.taskStopErrors,
            onRefresh: (serverId) => void serverActions.requestRefresh(serverId),
            onRestart: (serverId) => void serverActions.requestRestart(serverId),
            onStopTask: (serverId, taskId, taskName) => void serverActions.requestStopTask(serverId, taskId, taskName),
          }}
        />
        <LiveStreamList servers={servers} />
      </QueryStateBoundary>
      {confirmation.dialog}
    </WorkspacePage>
  );
}

export { EmbyLivePage };
