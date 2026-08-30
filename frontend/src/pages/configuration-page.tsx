import { ArrowRight, RefreshCw, Settings2 } from "@/components/ui/icons";
import { useCallback, useEffect, useRef, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";

import { Button } from "@/components/ui/button";
import { QueryStateBoundary } from "@/components/ui/query-state-boundary";
import { useConfirmationDialog } from "@/components/ui/use-confirmation-dialog";
import { WorkspaceHeading } from "@/components/ui/workspace-heading";
import { WorkspacePage } from "@/components/ui/workspace-layout";
import { AccountsWorkspace } from "@/features/account-management/components/accounts-workspace";
import { AutomationsPanel } from "@/features/configuration/components/automations-panel";
import { ConfigurationTabs } from "@/features/configuration/components/configuration-tabs";
import { EmbyServersPanel } from "@/features/configuration/components/emby-servers-panel";
import { ServiceSettingsPanel } from "@/features/configuration/components/service-settings-panel";
import { TelegramPanel } from "@/features/configuration/components/telegram-panel";
import { testConfigurationConnections } from "@/features/configuration/api";
import { configurationTabHasDraft } from "@/features/configuration/configuration-draft-guard";
import { configurationPath, configurationTabFromRoute } from "@/features/configuration/configuration-navigation";
import { useConfigurationSettings } from "@/features/configuration/use-configuration-settings";
import { useEmbyServers } from "@/features/configuration/use-emby-servers";
import { EventBridgeWorkspace } from "@/features/event-bridge/components/event-bridge-workspace";
import { useNavigationPreferencesContext } from "@/features/navigation/use-navigation-preferences-context";
import { SystemStatusWorkspace } from "@/features/system-status/components/system-status-workspace";
import { useBeforeUnloadWarning } from "@/lib/use-before-unload-warning";
import { useUnsavedChangesNavigationGuard } from "@/lib/use-unsaved-changes-navigation-guard";

function ConfigurationPage() {
  const { tab: routeTab } = useParams();
  const activeTab = configurationTabFromRoute(routeTab);
  const previousTabRef = useRef(activeTab);
  const navigate = useNavigate();
  const confirmation = useConfirmationDialog();
  const [notice, setNotice] = useState("");
  const [hasUnsavedChanges, setHasUnsavedChanges] = useState(false);
  const [refreshEpoch, setRefreshEpoch] = useState(0);
  const settings = useConfigurationSettings();
  const navigationPreferences = useNavigationPreferencesContext();
  const servers = useEmbyServers();
  const serverActionError = servers.remove.error;
  const headerRefreshVisible = activeTab === "servers" || activeTab === "telegram" || activeTab === "automations" || activeTab === "services";
  const currentSectionRefreshing = activeTab === "servers"
    ? servers.servers.isFetching
    : activeTab === "telegram"
      ? settings.telegram.isFetching
      : activeTab === "automations" || activeTab === "services"
        ? settings.settings.isFetching
        : false;

  useEffect(() => {
    if (previousTabRef.current === activeTab) return;
    previousTabRef.current = activeTab;
    setHasUnsavedChanges(false);
    setNotice("");
  }, [activeTab]);

  useBeforeUnloadWarning(hasUnsavedChanges);
  useUnsavedChangesNavigationGuard(hasUnsavedChanges, confirmation.confirm);

  async function refreshCurrent() {
    const protectsDraft = configurationTabHasDraft(activeTab);
    if (
      protectsDraft &&
      hasUnsavedChanges &&
      !await confirmation.confirm({
        title: "Modifiche non salvate",
        description: "Ricaricare questa sezione e perdere le modifiche in corso?",
        confirmLabel: "Ricarica sezione",
        tone: "danger",
      })
    ) return;
    setNotice("");
    if (protectsDraft) setRefreshEpoch((current) => current + 1);
    if (activeTab === "servers") void servers.refresh();
    else if (activeTab === "telegram") void settings.telegram.refetch();
    else if (activeTab === "automations" || activeTab === "services") void settings.settings.refetch();
  }

  const onDraftChange = useCallback((dirty: boolean) => setHasUnsavedChanges(dirty), []);
  const configurationReady = Boolean(settings.settings.data?.has_config);
  const automationUnavailable = activeTab === "automations" && Boolean(settings.settings.data) && !configurationReady;

  async function removeServer(serverId: string) {
    if (!await confirmation.confirm({ title: "Rimuovi server Emby", description: "Rimuovere questo server Emby e i dati associati?", confirmLabel: "Rimuovi server", tone: "danger" })) return;
    servers.remove.mutate(serverId);
  }

  return (
    <WorkspacePage className="configuration-page">
      <WorkspaceHeading
        context="Amministrazione"
        title="Configurazione"
        description="Server Emby, notifiche, automazioni, integrazioni e stato operativo in un'unica area ordinata."
        actions={headerRefreshVisible ? (
          <Button type="button" variant="secondary" size="compact" onClick={() => void refreshCurrent()} disabled={currentSectionRefreshing}>
            <RefreshCw className={currentSectionRefreshing ? "animate-spin" : ""} size={16} aria-hidden="true" />
            Aggiorna sezione
          </Button>
        ) : undefined}
      />
      <ConfigurationTabs active={activeTab} variant={navigationPreferences.preferences.secondary_navigation}>
        {activeTab === "servers" ? <>
          {serverActionError ? <div className="inline-alert inline-alert--error" role="alert">{serverActionError.message}</div> : null}
          <QueryStateBoundary error={servers.servers.error} hasData={Boolean(servers.servers.data)} loadingLabel="Caricamento server Emby..." retrying={servers.servers.isFetching} onRetry={() => void servers.servers.refetch()}>
            <EmbyServersPanel servers={servers.servers.data?.servers || []} loading={servers.servers.isLoading} creating={servers.create.isPending} updatingIds={servers.updatingIds} deletingIds={servers.deletingIds} onCreate={async (input) => { await servers.create.mutateAsync(input); }} onUpdate={async (serverId, input) => { await servers.update.mutateAsync({ serverId, input }); }} onDelete={(serverId) => { void removeServer(serverId); }} onRefresh={() => void servers.refresh()} onDirtyChange={onDraftChange} />
          </QueryStateBoundary>
        </> : null}
        {activeTab === "telegram" ? <TelegramPanel settings={settings.telegram.data} busy={settings.telegramAction.isPending} notice={notice} actionError={settings.telegramAction.error?.message || ""} loadError={settings.telegram.error} retrying={settings.telegram.isFetching} onRetry={() => void settings.telegram.refetch()} onAction={async (action) => { const payload = await settings.telegramAction.mutateAsync(action); setNotice(payload.message || "Configurazione Telegram aggiornata"); return payload; }} onDirtyChange={onDraftChange} /> : null}
        {activeTab === "automations" ? <QueryStateBoundary error={settings.settings.error} hasData={Boolean(settings.settings.data)} loadingLabel="Caricamento automazioni..." retrying={settings.settings.isFetching} onRetry={() => void settings.settings.refetch()}>
          {!automationUnavailable ? <AutomationsPanel key={`automations-${refreshEpoch}`} automations={settings.settings.data?.automations} requestRefresh={settings.settings.data?.request_refresh} saving={settings.saveAutomations.isPending} savedMessage={notice} onSave={async (value) => { const payload = await settings.saveAutomations.mutateAsync(value); setNotice(payload.message || "Automazioni aggiornate"); return payload.automations; }} onRefresh={refreshCurrent} onDirtyChange={onDraftChange} /> : null}
        </QueryStateBoundary> : null}
        {activeTab === "services" ? <QueryStateBoundary error={settings.settings.error} hasData={Boolean(settings.settings.data)} loadingLabel="Caricamento configurazione servizi..." retrying={settings.settings.isFetching} onRetry={() => void settings.settings.refetch()}>
          <ServiceSettingsPanel key={`services-${refreshEpoch}`} services={settings.settings.data?.services} saving={settings.saveServices.isPending} savedMessage={notice} onSave={async (value) => { const payload = await settings.saveServices.mutateAsync(value); setNotice(payload.message || "Configurazione servizi aggiornata"); return payload.services; }} onTestConnections={testConfigurationConnections} onRefreshSettings={() => void settings.settings.refetch()} onNotice={setNotice} onDirtyChange={onDraftChange} />
        </QueryStateBoundary> : null}
        {activeTab === "event-bridge" ? <EventBridgeWorkspace embedded onDirtyChange={onDraftChange} /> : null}
        {activeTab === "system-status" ? <SystemStatusWorkspace embedded /> : null}
        {activeTab === "accounts" ? <AccountsWorkspace /> : null}
      </ConfigurationTabs>
      {automationUnavailable ? (
        <div className="configuration-unavailable" role="status">
          <Settings2 size={18} aria-hidden="true" />
          <div>
            <strong>Automazioni non ancora disponibili</strong>
            <span>Completa il database e i servizi essenziali prima di pianificare le operazioni.</span>
          </div>
          <Button type="button" variant="secondary" size="compact" onClick={() => navigate(configurationPath("services"))}>
            Apri servizi <ArrowRight size={15} aria-hidden="true" />
          </Button>
        </div>
      ) : null}
      {confirmation.dialog}
    </WorkspacePage>
  );
}

export { ConfigurationPage };
