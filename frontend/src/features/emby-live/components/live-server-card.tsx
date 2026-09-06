import { CircleAlert, LoaderCircle, RefreshCw, RotateCw } from "@/components/ui/icons";

import { StatusBadge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { EmbyServerIcon } from "@/features/emby-live/components/emby-server-icon";
import { LiveServerTasks } from "@/features/emby-live/components/live-server-tasks";
import {
  formatLiveTime,
  serverPresentation,
} from "@/features/emby-live/presentation";
import type { EmbyLiveServer } from "@/features/emby-live/types";

type LiveServerCardControls = {
  refreshing: boolean;
  refreshError?: string;
  restarting: boolean;
  restartDisabled: boolean;
  stoppingTaskKeys: ReadonlySet<string>;
  taskStopErrors: Readonly<Record<string, string>>;
  onRefresh: () => void;
  onRestart: () => void;
  onStopTask: (taskId: string, taskName?: string) => void;
};

function LiveServerCard({
  server,
  controls,
}: {
  server: EmbyLiveServer;
  controls: LiveServerCardControls;
}) {
  const presentation = serverPresentation(server);
  const error = server.status.error || server.tasks_error || server.streams_error;
  const announcedError = [...new Set([error, controls.refreshError].filter(Boolean))].join(" · ");
  const lastAction = server.server.last_action;
  const lastCheck = formatLiveTime(server.status.last_check);
  const [lastCheckDate, lastCheckTime = ""] = lastCheck.split(", ");

  return (
    <article className={`emby-live-server emby-live-server--${presentation.severity}`}>
      <header>
        <span className="emby-live-server-icon"><EmbyServerIcon icon={server.server.icon} color={server.server.icon_color} iconStyle={server.server.icon_style} size={19} /></span>
        <div><h4>{server.server.name}</h4><p>{server.server.url || server.status.name || server.server.id}</p></div>
        <div className="emby-live-server-header-actions">
          <Button
            type="button"
            variant="ghost"
            size="icon"
            className="emby-live-server-refresh"
            title={`Aggiorna informazioni ${server.server.name}`}
            aria-label={`Aggiorna informazioni ${server.server.name}`}
            onClick={controls.onRefresh}
            disabled={controls.refreshing}
          >
            {controls.refreshing ? <LoaderCircle className="animate-spin" size={15} aria-hidden="true" /> : <RefreshCw size={15} aria-hidden="true" />}
          </Button>
          <StatusBadge severity={presentation.severity}>{presentation.label}</StatusBadge>
        </div>
      </header>
      <dl className="emby-live-server-facts">
        <div className="emby-live-server-fact-version"><dt>Versione</dt><dd>{server.status.version || "N/D"}</dd></div>
        <div className="emby-live-server-fact-check"><dt>Ultimo check</dt><dd><span>{lastCheckDate}</span>{lastCheckTime ? <span>{lastCheckTime}</span> : null}</dd></div>
        <div className="emby-live-server-fact-count"><dt>Stream</dt><dd>{server.streams.length}</dd></div>
        <div className="emby-live-server-fact-count"><dt>Attività</dt><dd>{server.running_tasks.length}</dd></div>
      </dl>
      {announcedError ? <p className="emby-live-server-error" role="alert"><CircleAlert size={15} aria-hidden="true" />{announcedError}</p> : null}
      <div className="emby-live-server-command">
        <Button
          type="button"
          requiresWriteAccess
          variant="ghost"
          size="compact"
          onClick={controls.onRestart}
          disabled={!server.server.enabled || controls.restartDisabled}
        >
          <RotateCw size={16} className={controls.restarting ? "animate-spin" : ""} aria-hidden="true" />
          {controls.restarting ? "Riavvio in corso..." : "Riavvia server"}
        </Button>
      </div>
      <div className="emby-live-last-action">
        {lastAction ? <><strong>Ultima operazione: {lastAction.name}</strong><span>{formatLiveTime(lastAction.timestamp)} · {lastAction.result || "N/D"}</span></> : <span>Nessuna operazione registrata.</span>}
      </div>
      <LiveServerTasks
        serverId={server.server.id}
        tasks={server.running_tasks}
        stoppingTaskKeys={controls.stoppingTaskKeys}
        taskStopErrors={controls.taskStopErrors}
        onStopTask={controls.onStopTask}
      />
    </article>
  );
}

export { LiveServerCard };
export type { LiveServerCardControls };
