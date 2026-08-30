import {
  Bell,
  DatabaseZap,
  RefreshCw,
  Rocket,
  SearchCheck,
} from "@/components/ui/icons";

import { Button } from "@/components/ui/button";
import { WorkspaceChoiceGroup } from "@/components/ui/workspace-choice-group";
import { WorkspaceHeading } from "@/components/ui/workspace-heading";
import { EmbyServerIcon } from "@/features/emby-live/components/emby-server-icon";
import { latestDisplayLimits } from "@/features/emby-latest/latest-display-preferences";
import type { LatestServer } from "@/features/emby-latest/types";

type LatestReleaseControlsProps = {
  servers: LatestServer[];
  selectedServer: string;
  displayLimit: number;
  maxMovies?: number;
  maxSeries?: number;
  loading: boolean;
  refreshing: boolean;
  notifying: boolean;
  workflowing: boolean;
  onServerChange: (serverId: string) => void;
  onLimitChange: (limit: number) => void;
  onRefresh: () => void;
  onNotify: () => void;
  onWorkflow: () => void;
  onVerify: () => void;
};

function LatestReleaseControls({
  servers,
  selectedServer,
  displayLimit,
  maxMovies,
  maxSeries,
  loading,
  refreshing,
  notifying,
  workflowing,
  onServerChange,
  onLimitChange,
  onRefresh,
  onNotify,
  onWorkflow,
  onVerify,
}: LatestReleaseControlsProps) {
  const actionBusy = refreshing || notifying || workflowing;

  return (
    <>
      <WorkspaceHeading
        actionsClassName="latest-workspace-actions"
        className="latest-workspace-header"
        level="section"
        context="Pubblicazioni Emby"
        title="Pubblicazioni"
        description="Film e serie TV aggiunti di recente nei server Emby connessi."
        actions={<>
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
          <Button
            type="button"
            requiresWriteAccess
            variant="secondary"
            size="compact"
            onClick={onNotify}
            disabled={notifying || loading || workflowing || refreshing}
          >
            <Bell
              size={16}
              className={notifying ? "animate-pulse" : ""}
              aria-hidden="true"
            />
            Invia notifiche
          </Button>
        </>}
      />
      {workflowing ? (
        <p className="latest-workflow-pending" role="status">
          Un workflow globale e' in corso. Aggiornamento e notifiche saranno
          nuovamente disponibili al termine.
        </p>
      ) : null}
      <div className="latest-server-controls">
        <WorkspaceChoiceGroup
          ariaLabel="Server Emby"
          className="latest-server-tabs"
          idPrefix="latest-server-tab"
          value={selectedServer}
          options={[
            ...servers.map((server) => ({
              id: server.id,
              content: <>
              <EmbyServerIcon
                icon={server.icon}
                color={server.icon_color}
                iconStyle={server.icon_style}
                size={14}
              />
              {server.name}
              </>,
            })),
            { id: "all", content: "Tutti" },
          ]}
          onChange={onServerChange}
        />
        <label className="latest-display-limit">
          Mostra
          <select
            value={displayLimit}
            onChange={(event) => onLimitChange(Number(event.target.value))}
          >
            {latestDisplayLimits.map((limit) => (
              <option key={limit} value={limit}>
                {limit}
              </option>
            ))}
          </select>
          <span>
            <DatabaseZap size={13} aria-hidden="true" />
            Max DB: {maxMovies || 0} film · {maxSeries || 0} serie
          </span>
        </label>
      </div>
    </>
  );
}

export { LatestReleaseControls };
