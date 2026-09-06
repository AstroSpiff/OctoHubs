import { RefreshCw } from "@/components/ui/icons";
import { useCallback, useMemo, useState } from "react";
import { useParams } from "react-router-dom";

import { Button } from "@/components/ui/button";
import { useConfirmationDialog } from "@/components/ui/use-confirmation-dialog";
import { WorkspaceHeading } from "@/components/ui/workspace-heading";
import { WorkspacePage } from "@/components/ui/workspace-layout";
import { ProbeDataPanel } from "@/features/probe/components/probe-data-panel";
import type { ProbeDataTab } from "@/features/probe/probe-data-tab-options";
import { LibraryProbeControls } from "@/features/probe/components/library-probe-controls";
import { RecentProbeControls } from "@/features/probe/components/recent-probe-controls";
import { ProbeSettings } from "@/features/probe/components/probe-settings";
import type { ProbeComboServerStatus } from "@/features/probe/components/probe-combo-card";
import { ProbeScopeTabs } from "@/features/probe/components/probe-scope-tabs";
import { ProbeWorkspace } from "@/features/probe/components/probe-workspace";
import {
  mergeProbeWorkerStatuses,
} from "@/features/probe/presentation";
import { useNavigationPreferencesContext } from "@/features/navigation/use-navigation-preferences-context";
import {
  probeScopeFromRoute,
} from "@/features/probe/probe-navigation";
import { selectedAvailableProbeServerId } from "@/features/probe/probe-server-selection";
import type { ProbeServer, ProbeWorkerStatus } from "@/features/probe/types";
import {
  useProbeLibraries,
  useProbeScopeData,
  useProbeConfig,
} from "@/features/probe/use-probe";
import { useProbeDataActions } from "@/features/probe/use-probe-data-actions";
import { useProbeContextSelection } from "@/features/probe/use-probe-context-selection";
import { useEmbyLive } from "@/features/emby-live/use-emby-live";
import { useBeforeUnloadWarning } from "@/lib/use-before-unload-warning";
import { useUnsavedChangesNavigationGuard } from "@/lib/use-unsaved-changes-navigation-guard";
import { useWorkspaceCapabilities } from "@/features/session/workspace-capabilities-context";

type ProbeWorkerKind = "combo" | "discovery" | "processing";

function ProbePage() {
  const { canMutate } = useWorkspaceCapabilities();
  const { scope: routeScope } = useParams();
  const scope = probeScopeFromRoute(routeScope);
  const confirmation = useConfirmationDialog();
  const navigationPreferences = useNavigationPreferencesContext();
  const live = useEmbyLive();
  const libraries = useProbeLibraries();
  const [probeConfigDirty, setProbeConfigDirty] = useState(false);
  const [recentConfigServerId, setRecentConfigServerId] = useState("");
  const [dataTab, setDataTab] = useState<ProbeDataTab>("queue");
  useBeforeUnloadWarning(probeConfigDirty);
  useUnsavedChangesNavigationGuard(probeConfigDirty, confirmation.confirm);
  const servers = useMemo<ProbeServer[]>(
    () =>
      Object.values(live.snapshot?.servers || {})
        .filter((server) => server.server.enabled)
        .map((server) => ({
          id: server.server.id,
          name: server.server.name,
          icon: server.server.icon,
          icon_style: server.server.icon_style,
          icon_color: server.server.icon_color,
        })),
    [live.snapshot],
  );
  const serverNames = useMemo(
    () => Object.fromEntries(servers.map((server) => [server.id, server.name])),
    [servers],
  );

  const confirmDiscardProbeConfigDraft = useCallback(async () => {
    if (!probeConfigDirty) return true;
    const confirmed = await confirmation.confirm({
      title: "Modifiche non salvate",
      description:
        "Cambiare contesto e perdere le modifiche alla configurazione Probe?",
      confirmLabel: "Abbandona modifiche",
      tone: "danger",
    });
    if (confirmed) setProbeConfigDirty(false);
    return confirmed;
  }, [confirmation, probeConfigDirty]);

  const context = useProbeContextSelection({
    servers,
    libraries: libraries.data,
    confirmDiscardRecentConfigDraft: confirmDiscardProbeConfigDraft,
    scope,
  });
  const {
    libraryServerId,
    recentServerId,
    selectedDiscoveryLibraryIds,
    selectedLibraryData,
    selectedProcessingLibraryIds,
    selectLibraryServer,
    selectRecentServer,
    setDiscoveryLibraries,
    setProcessingLibraries,
    targetIds,
  } = context;
  const data = useProbeScopeData(scope, targetIds, dataTab);
  const activeDataQuery =
    dataTab === "history"
      ? data.history
      : dataTab === "errors"
        ? data.errors
        : dataTab === "incomplete"
          ? data.incomplete
          : data.queue;
  const probeConfigServerId =
    scope === "recent"
      ? (recentServerId === "all"
          ? selectedAvailableProbeServerId(recentConfigServerId, servers) || null
          : recentServerId)
      : libraryServerId || null;
  const probeConfig = useProbeConfig(probeConfigServerId);
  const selectedServerName = servers.find(
    (server) => server.id === probeConfigServerId,
  )?.name;
  const dataActions = useProbeDataActions({
    scope,
    targetIds,
    data,
    confirm: confirmation.confirm,
  });
  const busy =
    data.action.isPending ||
    data.removeQueue.isPending ||
    data.clearHistory.isPending ||
    data.removeBlacklist.isPending ||
    data.retry.isPending ||
    data.retryBlacklisted.isPending ||
    dataActions.isRunningBulkAction ||
    dataActions.isRetryingMany;
  const error =
    live.error ||
    libraries.error ||
    probeConfig.error ||
    activeDataQuery.error ||
    data.action.error ||
    data.removeQueue.error ||
    data.clearHistory.error ||
    data.removeBlacklist.error ||
    data.retry.error ||
    data.retryBlacklisted.error;

  function statusesFor(workerKey: string): ProbeComboServerStatus[] {
    return targetIds.map((serverId) => {
      const server = live.snapshot?.servers[serverId];
      return {
        serverId,
        serverName:
          server?.server.name ||
          servers.find((candidate) => candidate.id === serverId)?.name ||
          "Server Emby",
        status: server?.probe_status?.[workerKey] as
          ProbeWorkerStatus | undefined,
      };
    });
  }

  function workerStatus(workerKey: string): ProbeWorkerStatus | undefined {
    return mergeProbeWorkerStatuses(
      statusesFor(workerKey).flatMap(({ status }) => (status ? [status] : [])),
    );
  }

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

  function run(path: string, body: Record<string, unknown> = {}) {
    data.action.mutate({ path, body });
  }

  function runLibraries(kind: ProbeWorkerKind, mode?: "smart" | "forced") {
    if (!libraryServerId) return;
    const path =
      kind === "combo"
        ? "/api/v1/emby/probe/libraries/combo/start"
        : kind === "discovery"
          ? "/api/v1/emby/probe/discovery/start"
          : "/api/v1/emby/probe/processing/start";
    const libraryIds =
      kind === "discovery"
        ? selectedDiscoveryLibraryIds
        : selectedProcessingLibraryIds;
    if (kind !== "combo" && !libraryIds.length) return;
    run(path, {
      server_id: libraryServerId,
      ...(libraryIds.length ? { libraries: libraryIds } : {}),
      ...(mode ? { mode } : {}),
    });
  }

  function stopLibraries(kind: ProbeWorkerKind) {
    if (!libraryServerId) return;
    const path =
      kind === "combo"
        ? "/api/v1/emby/probe/libraries/combo/stop"
        : kind === "discovery"
          ? "/api/v1/emby/probe/discovery/stop"
          : "/api/v1/emby/probe/processing/stop";
    run(path, { server_id: libraryServerId });
  }

  function runRecent(
    kind: ProbeWorkerKind,
    mode?: "smart" | "forced",
    all = recentServerId === "all",
  ) {
    const path = recentActionPath(kind, "start", all);
    run(path, {
      ...(all ? {} : { server_id: recentServerId }),
      ...(kind === "discovery" ? { limit: 200 } : {}),
      ...(mode ? { mode } : {}),
    });
  }

  function stopRecent(kind: ProbeWorkerKind, all = recentServerId === "all") {
    run(
      recentActionPath(kind, "stop", all),
      all ? {} : { server_id: recentServerId },
    );
  }

  const downloadUrl =
    scope === "libraries" && libraryServerId
      ? `/api/v1/emby/probe/export-csv?server_id=${encodeURIComponent(libraryServerId)}&scope=libraries`
      : undefined;

  return (
    <WorkspacePage className="probe-page">
      <WorkspaceHeading
        title="Media Probe"
        description="Individuazione, analisi e recupero dei file video, con stato live dei worker e gestione completa delle code."
        actions={<Button
          type="button"
          variant="secondary"
          size="compact"
          onClick={() => {
            void libraries.refetch();
            void data.refresh();
            if (!probeConfigDirty) void probeConfig.refetch();
            live.refresh();
          }}
          disabled={libraries.isFetching}
        >
          <RefreshCw
            size={16}
            className={libraries.isFetching ? "animate-spin" : ""}
            aria-hidden="true"
          />
          Aggiorna
        </Button>}
      />

      <ProbeScopeTabs
        value={scope}
        variant={navigationPreferences.preferences.secondary_navigation}
      >

      {error ? (
        <div className="inline-alert inline-alert--error" role="alert">
          {probeErrorMessage(error)}
        </div>
      ) : null}
      {data.action.data ? (
        <div
          className={`inline-alert inline-alert--${data.action.data.success ? "success" : "error"}`}
          role={data.action.data.success ? "status" : "alert"}
        >
          {data.action.data.message}
        </div>
      ) : null}
      {dataActions.retrySummary ? (
        <div
          className={`inline-alert inline-alert--${dataActions.retrySummary.tone}`}
          role="status"
        >
          {dataActions.retrySummary.message}
        </div>
      ) : null}
      {dataActions.bulkProgress ? (
        <div className="inline-alert inline-alert--info" role="status">
          {dataActions.bulkProgress.label}: {dataActions.bulkProgress.completed}/{dataActions.bulkProgress.total} server elaborati.
        </div>
      ) : null}
      {dataActions.bulkSummary ? (
        <div
          className={`inline-alert inline-alert--${dataActions.bulkSummary.tone}`}
          role="status"
        >
          {dataActions.bulkSummary.message}
        </div>
      ) : null}

      <ProbeWorkspace
        scope={scope}
        servers={servers}
        serverId={scope === "recent" ? recentServerId : libraryServerId}
        onServerChange={
          scope === "recent"
            ? selectRecentServer
            : selectLibraryServer
        }
      >
        {scope === "libraries" ? (
          <LibraryProbeControls
            libraries={selectedLibraryData}
            discoverySelected={selectedDiscoveryLibraryIds}
            processingSelected={selectedProcessingLibraryIds}
            discoveryStatus={selectedScopeStatus.discovery}
            processingStatus={selectedScopeStatus.processing}
            comboStatus={selectedScopeStatus.combo}
            comboServerStatuses={comboServerStatuses}
            disabled={busy || libraries.isFetching}
            canMutate={canMutate}
            onDiscoverySelectionChange={setDiscoveryLibraries}
            onProcessingSelectionChange={setProcessingLibraries}
            onRunCombo={(mode) => runLibraries("combo", mode)}
            onStopCombo={() => stopLibraries("combo")}
            onRunDiscovery={() => runLibraries("discovery")}
            onStopDiscovery={() => stopLibraries("discovery")}
            onRunProcessing={(mode) => runLibraries("processing", mode)}
            onStopProcessing={() => stopLibraries("processing")}
          />
        ) : (
          <RecentProbeControls
            allServersSelected={recentServerId === "all"}
            serverCount={servers.length}
            selectedServer={servers.find((server) => server.id === recentServerId)}
            comboStatus={selectedScopeStatus.combo}
            discoveryStatus={selectedScopeStatus.discovery}
            processingStatus={selectedScopeStatus.processing}
            comboServerStatuses={comboServerStatuses}
            disabled={busy || !targetIds.length}
            canMutate={canMutate}
            onRunCombo={(mode) => runRecent("combo", mode)}
            onStopCombo={() => stopRecent("combo")}
            onRunDiscovery={() => runRecent("discovery")}
            onStopDiscovery={() => stopRecent("discovery")}
            onRunProcessing={(mode) => runRecent("processing", mode)}
            onStopProcessing={() => stopRecent("processing")}
          />
        )}
      </ProbeWorkspace>

      <ProbeDataPanel
        scope={scope}
        queue={data.queue.data || []}
        queueLoaded={data.queue.isFetched}
        history={data.history.data || []}
        historyLoaded={data.history.isFetched}
        errors={data.errors.data || []}
        errorsLoaded={data.errors.isFetched}
        incomplete={data.incomplete.data || []}
        incompleteLoaded={data.incomplete.isFetched}
        serverNames={serverNames}
        loading={
          activeDataQuery.isFetching && !activeDataQuery.isFetchingNextPage
        }
        hasMore={Boolean(activeDataQuery.hasNextPage)}
        loadingMore={activeDataQuery.isFetchingNextPage}
        busy={busy}
        downloadUrl={downloadUrl}
        settings={
          <ProbeSettings
            key={`${scope}:${probeConfigServerId || "all"}`}
            scope={scope}
            serverName={selectedServerName}
            config={probeConfig.data?.config}
            disabled={
              !probeConfigServerId
              || !probeConfig.isSuccess
              || !probeConfig.data?.config
            }
            loading={Boolean(probeConfigServerId) && probeConfig.isPending}
            loadError={probeConfig.error?.message}
            saving={data.saveConfig.isPending}
            error={data.saveConfig.error?.message}
            saved={Boolean(data.saveConfig.data?.success) && !data.saveConfig.error}
            configServers={
              scope === "recent" && recentServerId === "all" ? servers : undefined
            }
            configServerId={
              scope === "recent" && recentServerId === "all"
                ? probeConfigServerId || undefined
                : undefined
            }
            onConfigServerChange={
              scope === "recent" && recentServerId === "all"
                ? async (nextServerId) => {
                    if (nextServerId === probeConfigServerId) return true;
                    if (!(await confirmDiscardProbeConfigDraft())) return false;
                    setRecentConfigServerId(nextServerId);
                    return true;
                  }
                : undefined
            }
            onDirtyChange={setProbeConfigDirty}
            onSave={async (config) => {
              if (!probeConfigServerId) return config;
              return (await data.saveConfig.mutateAsync({
                serverId: probeConfigServerId,
                config,
              })).config;
            }}
          />
        }
        onRefresh={() => void data.refresh()}
        onLoadMore={() => void activeDataQuery.fetchNextPage()}
        onActiveTabChange={setDataTab}
        onClearQueue={() => void dataActions.clearQueue()}
        onClearHistory={() => void dataActions.clearHistory()}
        onClearBlacklist={(type) => void dataActions.clearBlacklist(type)}
        retryProgress={dataActions.retryProgress}
        onRemoveQueue={(item) => void dataActions.removeQueueItem(item)}
        onRemoveBlacklist={(type, item) =>
          void dataActions.removeBlacklistItem(type, item)
        }
        onRetryHistory={dataActions.retryHistoryItem}
        onRetryBlacklist={dataActions.retryBlacklistItem}
        onRetryMany={(items) => void dataActions.retryMany(items)}
        onBeforeTabChange={confirmDiscardProbeConfigDraft}
      />
      </ProbeScopeTabs>
      {confirmation.dialog}
    </WorkspacePage>
  );
}

function recentActionPath(
  kind: ProbeWorkerKind,
  action: "start" | "stop",
  all: boolean,
): string {
  const base =
    kind === "combo"
      ? "/api/v1/emby/probe/recent/combo"
      : kind === "discovery"
        ? "/api/v1/emby/probe/recent"
        : "/api/v1/emby/probe/recent/processing";
  return `${base}/${action}${all ? "-all" : ""}`;
}

function probeErrorMessage(error: Error | string): string {
  return typeof error === "string" ? error : error.message;
}

export { ProbePage };
