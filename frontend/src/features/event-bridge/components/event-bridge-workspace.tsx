import { Check, Cable, RefreshCw } from "@/components/ui/icons";
import { useEffect } from "react";

import { StatusBadge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { WorkspaceHeading } from "@/components/ui/workspace-heading";
import { WorkspaceSection } from "@/components/ui/workspace-layout";
import { WorkspaceStatusOverview } from "@/components/ui/workspace-status-overview";
import { EventBridgeServerCard } from "@/features/event-bridge/components/event-bridge-server-card";
import { useEventBridge } from "@/features/event-bridge/use-event-bridge";
import { useConfirmationDialog } from "@/components/ui/use-confirmation-dialog";
import { useBeforeUnloadWarning } from "@/lib/use-before-unload-warning";
import { useUnsavedChangesNavigationGuard } from "@/lib/use-unsaved-changes-navigation-guard";
import { cn } from "@/lib/utils";

function EventBridgeWorkspace({ embedded = false, onDirtyChange }: { embedded?: boolean; onDirtyChange?: (dirty: boolean) => void }) {
  const bridge = useEventBridge();
  const confirmation = useConfirmationDialog();
  const dirty = bridge.dirtyIds.size > 0;
  useBeforeUnloadWarning(dirty);
  useUnsavedChangesNavigationGuard(!embedded && dirty, confirmation.confirm);

  useEffect(() => {
    onDirtyChange?.(dirty);
    return () => onDirtyChange?.(false);
  }, [dirty, onDirtyChange]);

  const serverCount = bridge.servers.length;
  const connectedCount = bridge.status.data?.connected || 0;
  const credentialCount = bridge.status.data?.credential_configured || 0;
  const pendingChanges = bridge.dirtyIds.size;
  const heading = <EventBridgeHeading refreshing={bridge.status.isFetching} onRefresh={() => void bridge.status.refetch()} />;

  return <WorkspaceSection id={embedded ? "event-bridge-configuration" : undefined} className={embedded ? "embedded-workspace event-bridge-workspace" : "event-bridge-workspace"} tabIndex={embedded ? -1 : undefined}>
    {heading}
    <WorkspaceStatusOverview
      aria-live="polite"
      className="bridge-overview"
      description="Stato aggiornato automaticamente dai plugin configurati."
      icon={<Cable size={22} aria-hidden="true" />}
      iconTone={connectedCount ? "ok" : "warning"}
      metrics={[
        { label: "Server configurati", value: serverCount },
        {
          label: "WebSocket",
          tone: serverCount && connectedCount === serverCount ? "ok" : connectedCount ? "warning" : "neutral",
          value: serverCount ? `${connectedCount}/${serverCount}` : "Nessuno",
        },
        {
          label: "Modifiche da salvare",
          tone: pendingChanges ? "warning" : "neutral",
          value: pendingChanges || "Nessuna",
        },
        {
          label: "Credenziali",
          tone: serverCount && credentialCount === serverCount ? "ok" : "warning",
          value: serverCount ? `${credentialCount}/${serverCount}` : "Nessuna",
        },
      ]}
      status={<StatusBadge severity={connectedCount ? "ok" : "warning"}>{connectedCount ? "Connesso" : "In attesa"}</StatusBadge>}
      title="Collegamenti Event Bridge"
    />
    {bridge.notice ? <div className={`inline-alert inline-alert--${bridge.notice.tone}`} role="status"><Check size={17} aria-hidden="true" /> {bridge.notice.message}</div> : null}
    {bridge.status.error ? <div className="inline-alert inline-alert--error" role="alert">{bridge.status.error.message}</div> : null}
    {bridge.status.isLoading ? <div className="loading-state">Caricamento Event Bridge...</div> : null}
    <div className="bridge-servers">
      {bridge.servers.map((server) => {
        const saving = bridge.save.isPending && bridge.save.variables?.serverId === server.id;
        const saveError = bridge.save.isError && bridge.save.variables?.serverId === server.id
          ? bridge.save.error.message
          : "";
        const provisioning = bridge.provision.isPending && bridge.provision.variables === server.id;
        const provisionError = bridge.provision.isError && bridge.provision.variables === server.id
          ? bridge.provision.error.message
          : "";
        return (
          <EventBridgeServerCard
            key={server.id}
            server={server}
            draft={bridge.drafts[server.id] || server.settings}
            dirty={bridge.dirtyIds.has(server.id)}
            saving={saving}
            locked={bridge.save.isPending}
            saveError={saveError}
            provisioning={provisioning}
            provisionError={provisionError}
            onChange={(settings) => bridge.updateDraft(server.id, settings)}
            onSave={() => bridge.save.mutate({
              serverId: server.id,
              settings: bridge.drafts[server.id] || server.settings,
            })}
            onProvision={() => bridge.provision.mutate(server.id)}
          />
        );
      })}
    </div>
    {confirmation.dialog}
  </WorkspaceSection>;
}

function EventBridgeHeading({ refreshing, onRefresh }: { refreshing: boolean; onRefresh: () => void }) {
  return <WorkspaceHeading level="section" context="Integrazione Emby" title="Event Bridge" description="Stato del collegamento, configurazione effettiva del plugin e invio delle modifiche senza ricaricare la pagina." actions={<Button type="button" variant="secondary" size="compact" onClick={onRefresh} disabled={refreshing}><RefreshCw className={cn(refreshing && "animate-spin")} size={16} aria-hidden="true" />Aggiorna stato</Button>} />;
}

export { EventBridgeWorkspace };
