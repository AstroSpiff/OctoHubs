import { Server } from "@/components/ui/icons";

import { WorkspaceHeading } from "@/components/ui/workspace-heading";
import { LiveServerCard } from "@/features/emby-live/components/live-server-card";
import type { LiveServerCardControls } from "@/features/emby-live/components/live-server-card";
import type { EmbyLiveServer } from "@/features/emby-live/types";

type LiveServerListControls = Omit<LiveServerCardControls, "refreshing" | "refreshError" | "restarting" | "onRefresh" | "onRestart" | "onStopTask"> & {
  refreshingServerIds: ReadonlySet<string>;
  refreshErrors: Readonly<Record<string, string>>;
  restartingServerId: string | null;
  onRefresh: (serverId: string) => void;
  onRestart: (serverId: string) => void;
  onStopTask: (serverId: string, taskId: string, taskName?: string) => void;
};

function LiveServerList({
  servers,
  controls,
}: {
  servers: EmbyLiveServer[];
  controls: LiveServerListControls;
}) {
  return (
    <section id="emby-live-servers" className="emby-live-servers" aria-labelledby="emby-live-servers-title" tabIndex={-1}>
      <WorkspaceHeading
        className="emby-live-section-heading"
        level="subsection"
        context="Disponibilità e comandi"
        leading={<Server size={18} aria-hidden="true" />}
        title="Server Emby"
        titleId="emby-live-servers-title"
        actions={<span className="emby-live-section-count">{servers.length}</span>}
      />
      {!servers.length ? <p className="emby-live-empty">Nessun server Emby configurato.</p> : null}
      <div className="emby-live-server-grid">
        {servers.map((server) => (
          <LiveServerCard
            key={server.server.id}
            server={server}
            controls={{
              refreshing: controls.refreshingServerIds.has(server.server.id),
              refreshError: controls.refreshErrors[server.server.id],
              restarting: controls.restartingServerId === server.server.id,
              restartDisabled: controls.restartDisabled,
              stoppingTaskKeys: controls.stoppingTaskKeys,
              taskStopErrors: controls.taskStopErrors,
              onRefresh: () => controls.onRefresh(server.server.id),
              onRestart: () => controls.onRestart(server.server.id),
              onStopTask: (taskId, taskName) => controls.onStopTask(server.server.id, taskId, taskName),
            }}
          />
        ))}
      </div>
    </section>
  );
}

export { LiveServerList };
