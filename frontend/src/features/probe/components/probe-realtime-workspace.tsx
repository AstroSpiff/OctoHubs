import { useEffect, useMemo, useRef } from "react";

import { QueryStateBoundary } from "@/components/ui/query-state-boundary";
import { useEmbyLive } from "@/features/emby-live/use-emby-live";
import { LibraryProbeControls } from "@/features/probe/components/library-probe-controls";
import type { ProbeComboServerStatus } from "@/features/probe/components/probe-combo-card";
import { ProbeWorkspace } from "@/features/probe/components/probe-workspace";
import { RecentProbeControls } from "@/features/probe/components/recent-probe-controls";
import { mergeProbeWorkerStatuses } from "@/features/probe/presentation";
import type {
  ProbeLibrary,
  ProbeScope,
  ProbeServer,
  ProbeWorkerStatus,
} from "@/features/probe/types";

type ProbeMode = "smart" | "forced";

type ProbeRealtimeWorkspaceProps = {
  scope: ProbeScope;
  serverId: string;
  targetIds: string[];
  libraries: ProbeLibrary[];
  discoverySelected: string[];
  processingSelected: string[];
  busy: boolean;
  librariesFetching: boolean;
  canMutate: boolean;
  refreshRequest: number;
  onServersChange: (servers: ProbeServer[]) => void;
  onServerChange: (serverId: string) => boolean | void | Promise<boolean | void>;
  onDiscoverySelectionChange: (ids: string[]) => void;
  onProcessingSelectionChange: (ids: string[]) => void;
  onRunCombo: (mode: ProbeMode) => void;
  onStopCombo: () => void;
  onRunDiscovery: () => void;
  onStopDiscovery: () => void;
  onRunProcessing: (mode: ProbeMode) => void;
  onStopProcessing: () => void;
};

function ProbeRealtimeWorkspace({
  scope,
  serverId,
  targetIds,
  libraries,
  discoverySelected,
  processingSelected,
  busy,
  librariesFetching,
  canMutate,
  refreshRequest,
  onServersChange,
  onServerChange,
  onDiscoverySelectionChange,
  onProcessingSelectionChange,
  onRunCombo,
  onStopCombo,
  onRunDiscovery,
  onStopDiscovery,
  onRunProcessing,
  onStopProcessing,
}: ProbeRealtimeWorkspaceProps) {
  const { snapshot, error, connection, refresh } = useEmbyLive();
  const handledRefreshRequest = useRef(refreshRequest);
  const reportedServerIdentity = useRef("");
  const servers = useMemo<ProbeServer[]>(
    () =>
      Object.values(snapshot?.servers || {})
        .filter((server) => server.server.enabled)
        .map((server) => ({
          id: server.server.id,
          name: server.server.name,
          icon: server.server.icon,
          icon_style: server.server.icon_style,
          icon_color: server.server.icon_color,
        })),
    [snapshot],
  );
  const serverIdentity = servers
    .map((server) => [
      server.id,
      server.name,
      server.icon || "",
      server.icon_style || "",
      server.icon_color || "",
    ].join("\u0000"))
    .join("\u0001");

  useEffect(() => {
    if (reportedServerIdentity.current === serverIdentity) return;
    reportedServerIdentity.current = serverIdentity;
    onServersChange(servers);
  }, [onServersChange, serverIdentity, servers]);

  useEffect(() => {
    if (handledRefreshRequest.current === refreshRequest) return;
    handledRefreshRequest.current = refreshRequest;
    refresh();
  }, [refresh, refreshRequest]);

  const statusesFor = (workerKey: string): ProbeComboServerStatus[] =>
    targetIds.map((targetServerId) => {
      const server = snapshot?.servers[targetServerId];
      return {
        serverId: targetServerId,
        serverName:
          server?.server.name ||
          servers.find((candidate) => candidate.id === targetServerId)?.name ||
          "Server Emby",
        status: server?.probe_status?.[workerKey] as
          | ProbeWorkerStatus
          | undefined,
      };
    });
  const workerStatus = (workerKey: string): ProbeWorkerStatus | undefined =>
    mergeProbeWorkerStatuses(
      statusesFor(workerKey).flatMap(({ status }) => (status ? [status] : [])),
    );
  const workerKeys =
    scope === "libraries"
      ? {
          combo: "combo_libraries",
          discovery: "discovery",
          processing: "processing",
        }
      : {
          combo: "combo_recent",
          discovery: "recent_discovery",
          processing: "recent_processing",
        };
  const selectedScopeStatus = {
    combo: workerStatus(workerKeys.combo),
    discovery: workerStatus(workerKeys.discovery),
    processing: workerStatus(workerKeys.processing),
  };
  const comboServerStatuses = statusesFor(workerKeys.combo);

  return (
    <QueryStateBoundary
      error={error ? new Error(error) : null}
      hasData={Boolean(snapshot)}
      loadingLabel="Caricamento server Emby..."
      retrying={connection === "loading"}
      onRetry={refresh}
    >
      <ProbeWorkspace
        scope={scope}
        servers={servers}
        serverId={serverId}
        onServerChange={onServerChange}
      >
        {scope === "libraries" ? (
          <LibraryProbeControls
            libraries={libraries}
            discoverySelected={discoverySelected}
            processingSelected={processingSelected}
            discoveryStatus={selectedScopeStatus.discovery}
            processingStatus={selectedScopeStatus.processing}
            comboStatus={selectedScopeStatus.combo}
            comboServerStatuses={comboServerStatuses}
            disabled={busy || librariesFetching}
            canMutate={canMutate}
            onDiscoverySelectionChange={onDiscoverySelectionChange}
            onProcessingSelectionChange={onProcessingSelectionChange}
            onRunCombo={onRunCombo}
            onStopCombo={onStopCombo}
            onRunDiscovery={onRunDiscovery}
            onStopDiscovery={onStopDiscovery}
            onRunProcessing={onRunProcessing}
            onStopProcessing={onStopProcessing}
          />
        ) : (
          <RecentProbeControls
            allServersSelected={serverId === "all"}
            serverCount={servers.length}
            selectedServer={servers.find((server) => server.id === serverId)}
            comboStatus={selectedScopeStatus.combo}
            discoveryStatus={selectedScopeStatus.discovery}
            processingStatus={selectedScopeStatus.processing}
            comboServerStatuses={comboServerStatuses}
            disabled={busy || !targetIds.length}
            canMutate={canMutate}
            onRunCombo={onRunCombo}
            onStopCombo={onStopCombo}
            onRunDiscovery={onRunDiscovery}
            onStopDiscovery={onStopDiscovery}
            onRunProcessing={onRunProcessing}
            onStopProcessing={onStopProcessing}
          />
        )}
      </ProbeWorkspace>
    </QueryStateBoundary>
  );
}

export { ProbeRealtimeWorkspace };
export type { ProbeRealtimeWorkspaceProps };
