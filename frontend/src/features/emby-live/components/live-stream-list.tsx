import { PlayCircle } from "@/components/ui/icons";

import { WorkspaceHeading } from "@/components/ui/workspace-heading";
import { LiveStreamRow } from "@/features/emby-live/components/live-stream-row";
import type { EmbyLiveServer } from "@/features/emby-live/types";

function LiveStreamList({ servers }: { servers: EmbyLiveServer[] }) {
  const streams = servers.flatMap((server) => server.streams.map((stream) => ({ ...stream, serverName: server.server.name, serverId: server.server.id })));
  return (
    <section className="emby-live-streams" aria-labelledby="emby-live-streams-title">
      <WorkspaceHeading
        className="emby-live-section-heading"
        level="subsection"
        context="Riproduzioni correnti"
        leading={<PlayCircle size={18} aria-hidden="true" />}
        title="Stream attivi"
        titleId="emby-live-streams-title"
        actions={<span className="emby-live-section-count">{streams.length}</span>}
      />
      {!streams.length ? <p className="emby-live-empty">Nessuna riproduzione attiva.</p> : null}
      <div className="emby-live-stream-list">{streams.map((stream) => <LiveStreamRow key={`${stream.serverId}-${stream.session_id}`} stream={stream} />)}</div>
    </section>
  );
}

export { LiveStreamList };
