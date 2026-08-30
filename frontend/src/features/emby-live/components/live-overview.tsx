import { Radio, RefreshCw, Wifi, WifiOff } from "@/components/ui/icons";

import { StatusBadge } from "@/components/ui/badge";
import { WorkspaceStatusOverview } from "@/components/ui/workspace-status-overview";
import { formatLiveTime } from "@/features/emby-live/presentation";
import type { EmbyLiveServer, LiveConnectionState } from "@/features/emby-live/types";

function LiveOverview({ servers, connection, updatedAt }: { servers: EmbyLiveServer[]; connection: LiveConnectionState; updatedAt: number }) {
  const online = servers.filter((server) => server.server.enabled && server.status.ok).length;
  const streams = servers.reduce((total, server) => total + server.streams.length, 0);
  const runningTasks = servers.reduce((total, server) => total + server.running_tasks.length, 0);
  const connected = connection === "connected";
  const fallback = connection === "fallback";
  const label = connected
    ? "Aggiornamenti in diretta"
    : fallback
      ? "Aggiornamento periodico"
      : connection === "loading"
        ? "Connessione in corso"
        : "Riconnessione in corso";

  return (
    <WorkspaceStatusOverview
      aria-live="polite"
      className="emby-live-overview"
      description={updatedAt ? `Ultimo dato: ${formatLiveTime(new Date(updatedAt).toISOString())}` : "In attesa del primo dato"}
      icon={connected ? <Wifi size={22} aria-hidden="true" /> : fallback ? <RefreshCw size={22} aria-hidden="true" /> : <WifiOff size={22} aria-hidden="true" />}
      iconTone={connected ? "ok" : fallback ? "info" : "warning"}
      metrics={[
        { label: "Server online", value: `${online}/${servers.filter((server) => server.server.enabled).length}` },
        { label: "Stream attivi", value: streams },
        { label: "Attività in corso", value: runningTasks },
        { label: <><Radio size={13} aria-hidden="true" /> Feed</>, value: connected ? "Live" : fallback ? "HTTP" : <RefreshCw size={16} className="animate-spin" aria-label="Riconnessione" /> },
      ]}
      status={<StatusBadge severity={connected ? "ok" : fallback ? "info" : "warning"}>{connected ? "Connesso" : fallback ? "Periodico" : "In attesa"}</StatusBadge>}
      title={label}
    />
  );
}

export { LiveOverview };
