import { Filter, RotateCcw } from "@/components/ui/icons";

import { Button } from "@/components/ui/button";
import {
  WorkspaceToolbar,
  WorkspaceToolbarField,
  WorkspaceToolbarGroup,
  WorkspaceToolbarRow,
} from "@/components/ui/workspace-toolbar";
import type { StreamStatsFilters } from "@/features/stream-stats/types";

type StreamStatsFiltersProps = {
  filters: StreamStatsFilters;
  facets: {
    servers: Array<{ id: string; name: string; count: number }>;
    users: Array<{ id: string; name: string; count: number }>;
    clients: Array<{ id: string; name: string; count: number }>;
  };
  onChange: (changes: Partial<StreamStatsFilters>) => void;
  onReset: () => void;
};

type FacetSelectProps = {
  label: string;
  value: string;
  options: Array<{ id: string; name: string; count: number }>;
  empty: string;
  onChange: (value: string) => void;
};

function StreamStatsFilters({ filters, facets, onChange, onReset }: StreamStatsFiltersProps) {
  return (
    <WorkspaceToolbar className="stream-stats-filters" aria-label="Filtra statistiche stream">
      <WorkspaceToolbarRow className="stream-stats-filter-row">
        <WorkspaceToolbarGroup
          className="stream-stats-filter-group"
          label={<><Filter size={15} aria-hidden="true" /> Filtra</>}
        >
          <WorkspaceToolbarField className="stream-stats-field stream-stats-period" label="Periodo">
            <select className="workspace-toolbar-control" value={filters.period} onChange={(event) => onChange({ period: event.target.value as StreamStatsFilters["period"] })}>
              <option value="24h">24 ore</option>
              <option value="7d">7 giorni</option>
              <option value="30d">30 giorni</option>
              <option value="all">Tutto</option>
            </select>
          </WorkspaceToolbarField>
          <FacetSelect label="Server" value={filters.server_id} options={facets.servers} onChange={(server_id) => onChange({ server_id })} empty="Tutti i server" />
          <FacetSelect label="Utente" value={filters.user} options={facets.users} onChange={(user) => onChange({ user })} empty="Tutti gli utenti" />
          <FacetSelect label="Client" value={filters.client} options={facets.clients} onChange={(client) => onChange({ client })} empty="Tutti i client" />
          <label className="stream-stats-check" title="Mostra problemi e correzioni; nasconde stream corretti, semplici uscite e osservazioni neutre.">
            <input type="checkbox" checked={filters.issues_only} onChange={(event) => onChange({ issues_only: event.target.checked })} />
            <span>Solo problemi e correzioni</span>
          </label>
          <Button type="button" size="icon" variant="ghost" onClick={onReset} title="Ripristina filtri" aria-label="Ripristina filtri">
            <RotateCcw size={15} aria-hidden="true" />
          </Button>
        </WorkspaceToolbarGroup>
        <WorkspaceToolbarField className="stream-stats-sort" label="Ordina">
          <select
            className="workspace-toolbar-control"
            value={filters.sort}
            onChange={(event) => onChange({ sort: event.target.value as StreamStatsFilters["sort"] })}
          >
            <option value="issues_desc">Problemi</option>
            <option value="streams_desc">Stream</option>
            <option value="recent_desc">Recenti</option>
            <option value="user_asc">Utente A-Z</option>
          </select>
        </WorkspaceToolbarField>
      </WorkspaceToolbarRow>
    </WorkspaceToolbar>
  );
}

function FacetSelect({ label, value, options, empty, onChange }: FacetSelectProps) {
  return (
    <WorkspaceToolbarField className="stream-stats-field" label={label}>
      <select
        className="workspace-toolbar-control"
        value={value}
        onChange={(event) => onChange(event.target.value)}
      >
        <option value="">{empty}</option>
        {options.map((option) => <option key={option.id} value={option.id}>{option.name} ({option.count})</option>)}
      </select>
    </WorkspaceToolbarField>
  );
}

export { StreamStatsFilters };
