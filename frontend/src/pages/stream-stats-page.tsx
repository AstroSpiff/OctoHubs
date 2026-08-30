import { RefreshCw } from "@/components/ui/icons";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import { WorkspaceHeading } from "@/components/ui/workspace-heading";
import { WorkspacePage, WorkspaceSection } from "@/components/ui/workspace-layout";
import { StreamStatsFilters } from "@/features/stream-stats/components/stream-stats-filters";
import { StreamStatsHistory } from "@/features/stream-stats/components/stream-stats-history";
import { StreamStatsSummary } from "@/features/stream-stats/components/stream-stats-summary";
import { StreamStatsStreamDialog } from "@/features/stream-stats/components/stream-stats-stream-dialog";
import { StreamStatsUserList } from "@/features/stream-stats/components/stream-stats-user-list";
import { useStreamStats } from "@/features/stream-stats/use-stream-stats";

function StreamStatsPage() {
  const { stats, filters, updateFilters, resetFilters } = useStreamStats();
  const [selectedStreamId, setSelectedStreamId] = useState<string | null>(null);
  const data = stats.data;
  return (
    <WorkspacePage>
      <WorkspaceSection className="stream-stats-workspace" aria-labelledby="stream-stats-title" aria-busy={stats.isFetching}>
        <WorkspaceHeading
          actionsClassName="stream-stats-workspace-actions"
          className="stream-stats-workspace-header"
          level="section"
          title="Statistiche stream utenti"
          titleId="stream-stats-title"
          description="Leggi al volo chi riproduce correttamente, chi corregge e dove nascono più problemi."
          actions={<>
            {data && stats.isFetching ? <span className="stream-stats-updating" role="status">Aggiornamento dati...</span> : null}
            <Button type="button" size="icon" variant="secondary" onClick={() => void stats.refetch()} disabled={stats.isFetching} title="Aggiorna statistiche" aria-label="Aggiorna statistiche">
              <RefreshCw className={stats.isFetching ? "animate-spin" : ""} size={16} aria-hidden="true" />
            </Button>
          </>}
        />
        <StreamStatsFilters filters={filters} facets={data?.facets || { servers: [], users: [], clients: [] }} onChange={updateFilters} onReset={resetFilters} />
        {stats.error ? <div className="inline-alert inline-alert--error" role="alert">{stats.error.message}</div> : null}
        {stats.isLoading ? <div className="loading-state">Caricamento statistiche stream...</div> : null}
        {data ? <StreamStatsSummary summary={data.summary} /> : null}
        {data ? <div className="stream-stats-grid"><StreamStatsUserList users={data.users} onOpenStream={setSelectedStreamId} /><StreamStatsHistory history={data.history} /></div> : null}
      </WorkspaceSection>
      <StreamStatsStreamDialog streamId={selectedStreamId} onClose={() => setSelectedStreamId(null)} />
    </WorkspacePage>
  );
}

export { StreamStatsPage };
