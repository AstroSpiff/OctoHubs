import {
  Bell,
  RefreshCw,
  Rocket,
  SearchCheck,
} from "@/components/ui/icons";

import { Button } from "@/components/ui/button";
import { WorkspaceChoiceGroup } from "@/components/ui/workspace-choice-group";
import { WorkspaceHeading } from "@/components/ui/workspace-heading";
import { EmbyServerIcon } from "@/features/emby-live/components/emby-server-icon";
import type { LatestServer } from "@/features/emby-latest/types";

type LatestReleaseHeaderProps = {
  workflowing: boolean;
};

type LatestServerSelectorProps = {
  servers: LatestServer[];
  selectedServer: string;
  onServerChange: (serverId: string) => void;
};

type LatestPublicationActionsProps = {
  loading: boolean;
  refreshing: boolean;
  notifying: boolean;
  workflowing: boolean;
  onRefresh: () => void;
  onWorkflow: () => void;
  onVerify: () => void;
};

type LatestNotificationActionsProps = {
  loading: boolean;
  refreshing: boolean;
  notifying: boolean;
  workflowing: boolean;
  onNotify: () => void;
};

function LatestReleaseHeader({
  workflowing,
}: LatestReleaseHeaderProps) {
  return (
    <>
      <WorkspaceHeading
        className="latest-workspace-header"
        level="section"
        context="Pubblicazioni Emby"
        title="Pubblicazioni"
        description="Film e serie TV aggiunti di recente nei server Emby connessi."
      />
      {workflowing ? (
        <p className="latest-workflow-pending" role="status">
          Un workflow globale e' in corso. Aggiornamento e notifiche saranno
          nuovamente disponibili al termine.
        </p>
      ) : null}
    </>
  );
}

function LatestServerSelector({
  servers,
  selectedServer,
  onServerChange,
}: LatestServerSelectorProps) {
  return (
    <div className="latest-server-controls">
      <WorkspaceChoiceGroup
        ariaLabel="Server Emby"
        className="latest-server-tabs"
        idPrefix="latest-server-tab"
        value={selectedServer}
        options={[
          ...servers.map((server) => ({
            id: server.id,
            content: (
              <>
                <EmbyServerIcon
                  icon={server.icon}
                  color={server.icon_color}
                  iconStyle={server.icon_style}
                  size={14}
                />
                {server.name}
              </>
            ),
          })),
          { id: "all", content: "Tutti" },
        ]}
        onChange={onServerChange}
      />
    </div>
  );
}

function LatestPublicationActions({
  loading,
  refreshing,
  notifying,
  workflowing,
  onRefresh,
  onWorkflow,
  onVerify,
}: LatestPublicationActionsProps) {
  const actionBusy = refreshing || notifying || workflowing;

  return (
    <div className="latest-view-actions" aria-label="Azioni pubblicazioni">
      <Button
        type="button"
        requiresWriteAccess
        variant="primary"
        size="compact"
        onClick={onWorkflow}
        disabled={actionBusy}
      >
        <Rocket size={16} aria-hidden="true" />
        {workflowing ? "Workflow in corso..." : "Aggiorna tutto"}
      </Button>
      <Button
        type="button"
        requiresWriteAccess
        variant="secondary"
        size="compact"
        onClick={onRefresh}
        disabled={refreshing || loading || workflowing || notifying}
      >
        <RefreshCw
          size={16}
          className={refreshing ? "animate-spin" : ""}
          aria-hidden="true"
        />
        Aggiorna
      </Button>
      <Button
        type="button"
        variant="secondary"
        size="compact"
        onClick={onVerify}
        disabled={loading}
      >
        <SearchCheck size={16} aria-hidden="true" />
        Verifica dati
      </Button>
    </div>
  );
}

function LatestNotificationActions({
  loading,
  refreshing,
  notifying,
  workflowing,
  onNotify,
}: LatestNotificationActionsProps) {
  return (
    <div className="latest-view-actions" aria-label="Azioni notifiche Telegram">
      <Button
        type="button"
        requiresWriteAccess
        variant="primary"
        size="compact"
        onClick={onNotify}
        disabled={notifying || loading || workflowing || refreshing}
      >
        <Bell
          size={16}
          className={notifying ? "animate-pulse" : ""}
          aria-hidden="true"
        />
        {notifying ? "Invio in corso..." : "Invia notifiche"}
      </Button>
    </div>
  );
}

export {
  LatestNotificationActions,
  LatestPublicationActions,
  LatestReleaseHeader,
  LatestServerSelector,
};
