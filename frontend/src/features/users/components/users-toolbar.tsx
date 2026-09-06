import { CheckCheck, ChevronDown, RefreshCw, Search, Star, UserPlus, X } from "@/components/ui/icons";
import { useEffect, useRef, useState } from "react";

import { Button } from "@/components/ui/button";
import { WriteAction } from "@/features/session/workspace-capabilities";
import { useWorkspaceCapabilities } from "@/features/session/workspace-capabilities-context";
import {
  WorkspaceToolbar,
  WorkspaceToolbarActions,
  WorkspaceToolbarField,
  WorkspaceToolbarGroup,
  WorkspaceToolbarRow,
} from "@/components/ui/workspace-toolbar";
import type { UserAccessStatus, UsersDashboard, UsersFilters } from "@/features/users/types";
import type { IconProfile } from "@/features/user-icons/types";

type Option = { id: string; name: string };

type UsersToolbarProps = {
  data: UsersDashboard;
  filters: UsersFilters;
  selection: {
    visibleCount: number;
    selectedVisibleCount: number;
    leaderCount: number;
    selectedLeaderCount: number;
  };
  refreshing: boolean;
  iconProfiles: IconProfile[];
  onChange: (updates: Partial<UsersFilters>) => void;
  onSelectAll: () => void;
  onSelectLeaders: () => void;
  onDeselect: () => void;
  onCreate: () => void;
  onRefresh: () => void;
};

const sortOptions: Option[] = [
  { id: "name_asc_server_asc", name: "Utente A-Z, server A-Z" },
  { id: "name_asc_server_desc", name: "Utente A-Z, server Z-A" },
  { id: "name_desc_server_asc", name: "Utente Z-A, server A-Z" },
  { id: "name_desc_server_desc", name: "Utente Z-A, server Z-A" },
  { id: "server_asc_name_asc", name: "Server A-Z, utente A-Z" },
  { id: "server_asc_name_desc", name: "Server A-Z, utente Z-A" },
  { id: "server_desc_name_asc", name: "Server Z-A, utente A-Z" },
  { id: "server_desc_name_desc", name: "Server Z-A, utente Z-A" },
  { id: "members", name: "Numero utenti" },
];

function UsersToolbar({
  data,
  filters,
  selection,
  refreshing,
  iconProfiles,
  onChange,
  onSelectAll,
  onSelectLeaders,
  onDeselect,
  onCreate,
  onRefresh,
}: UsersToolbarProps) {
  const { canMutate } = useWorkspaceCapabilities();
  const allVisibleSelected = selection.visibleCount > 0 && selection.selectedVisibleCount === selection.visibleCount;
  const onlyLeadersSelected = selection.leaderCount > 0
    && selection.selectedLeaderCount === selection.leaderCount
    && selection.selectedVisibleCount === selection.selectedLeaderCount;

  return (
    <WorkspaceToolbar className="users-toolbar" aria-label="Gestione utenti">
      <WorkspaceToolbarRow className={`users-toolbar-primary${canMutate ? "" : " users-toolbar-primary--read-only"}`}>
        <WriteAction>
          <WorkspaceToolbarGroup className="users-selection-group" label="Selezione">
            <WorkspaceToolbarActions className="users-selection-actions" role="group" aria-label="Selezione rapida utenti">
              <Button type="button" variant="secondary" onClick={onSelectAll} title="Seleziona tutti gli utenti visibili" disabled={!selection.visibleCount} aria-pressed={allVisibleSelected}>
                <CheckCheck size={15} aria-hidden="true" />
                Tutti
              </Button>
              <Button type="button" variant="secondary" onClick={onSelectLeaders} title="Seleziona solo leader e utenti singoli visibili" disabled={!selection.leaderCount} aria-pressed={onlyLeadersSelected}>
                <Star size={15} aria-hidden="true" />
                Leader
              </Button>
              <Button type="button" variant="secondary" onClick={onDeselect} title="Deseleziona gli utenti visibili" disabled={!selection.selectedVisibleCount}>
                <X size={15} aria-hidden="true" />
                Desel.
              </Button>
            </WorkspaceToolbarActions>
          </WorkspaceToolbarGroup>
        </WriteAction>

        <WorkspaceToolbarGroup className="users-search-group" label="Ricerca">
          <span className="workspace-toolbar-search-control users-search">
            <Search size={16} aria-hidden="true" />
            <input
              aria-label="Cerca utenti o gruppi"
              value={filters.search}
              onChange={(event) => onChange({ search: event.target.value })}
              placeholder="Cerca utente o gruppo..."
            />
          </span>
        </WorkspaceToolbarGroup>

        <WorkspaceToolbarGroup className="users-actions-group" label="Azioni">
          <WorkspaceToolbarActions className="users-toolbar-actions">
            <Button type="button" requiresWriteAccess variant="primary" onClick={onCreate}>
              <UserPlus size={16} aria-hidden="true" />
              Crea utente
            </Button>
            <Button
              type="button"
              variant="secondary"
              size="icon"
              title="Aggiorna elenco utenti"
              aria-label="Aggiorna elenco utenti"
              onClick={onRefresh}
              disabled={refreshing}
            >
              <RefreshCw size={16} className={refreshing ? "animate-spin" : ""} aria-hidden="true" />
            </Button>
          </WorkspaceToolbarActions>
        </WorkspaceToolbarGroup>
      </WorkspaceToolbarRow>

      <details className="users-filter-group">
        <summary className="users-filter-summary">
          <span className="workspace-toolbar-label">Filtri e ordinamento</span>
          <ChevronDown size={15} aria-hidden="true" />
        </summary>
        <div className="users-filter-controls">
          <MultiSelect className="users-filter-field--server" label="Server" values={filters.serverIds} options={data.servers} onChange={(serverIds) => onChange({ serverIds })} />
          <MultiSelect
            className="users-filter-field--status"
            label="Stato"
            values={filters.statuses}
            options={[
              { id: "active", name: "Attivi" },
              { id: "remote_disabled", name: "Remoto disabilitato" },
              { id: "account_disabled", name: "Account disabilitato" },
            ]}
            onChange={(statuses) => onChange({ statuses: statuses as UserAccessStatus[] })}
          />
          <MultiSelect
            className="users-filter-field--icon-profile"
            label="Profilo icona"
            values={filters.iconProfileIds}
            options={[{ id: "none", name: "Nessun profilo" }, ...iconProfiles.map((profile) => ({ id: profile.id, name: profile.label }))]}
            onChange={(iconProfileIds) => onChange({ iconProfileIds })}
          />
          <div className="users-filter-select-stack">
            <SelectField
              className="users-filter-field--type"
              label="Tipo"
              value={filters.groupType}
              onChange={(value) => onChange({ groupType: value as UsersFilters["groupType"] })}
              options={[
                { id: "all", name: "Tutti gli utenti" },
                { id: "single", name: "Utenti singoli" },
                { id: "linked", name: "Gruppi associati" },
              ]}
            />
            <SelectField
              className="users-filter-field--sort"
              label="Ordina"
              value={filters.sort}
              onChange={(value) => onChange({ sort: value as UsersFilters["sort"] })}
              options={sortOptions}
            />
          </div>
        </div>
      </details>
    </WorkspaceToolbar>
  );
}

function SelectField({ className, label, value, options, onChange }: { className?: string; label: string; value: string; options: Option[]; onChange: (value: string) => void }) {
  return (
    <WorkspaceToolbarField className={`users-filter-field ${className || ""}`} label={label}>
      <select className="workspace-toolbar-control" aria-label={label} value={value} onChange={(event) => onChange(event.target.value)}>
        {options.map((option) => <option key={option.id} value={option.id}>{option.name}</option>)}
      </select>
    </WorkspaceToolbarField>
  );
}

function MultiSelect({ className, label, values, options, onChange }: { className?: string; label: string; values: string[]; options: Option[]; onChange: (values: string[]) => void }) {
  function toggleOption(optionId: string) {
    const next = new Set(values);
    if (next.has(optionId)) next.delete(optionId);
    else next.add(optionId);
    onChange(options.filter((option) => next.has(option.id)).map((option) => option.id));
  }

  return (
    <div className={`workspace-toolbar-field users-filter-field users-filter-field--multi ${className || ""}`}>
      <div className="users-filter-label-row">
        <span className="workspace-toolbar-label">{label}</span>
        {values.length ? (
          <button
            type="button"
            className="users-filter-clear"
            title={`Azzera filtro ${label}`}
            aria-label={`Azzera filtro ${label}`}
            onClick={() => onChange([])}
          >
            <X size={14} aria-hidden="true" />
          </button>
        ) : null}
      </div>
      <MultiSelectOptions label={label} options={options} values={values} onToggle={toggleOption} />
    </div>
  );
}

function MultiSelectOptions({ label, options, values, onToggle }: {
  label: string;
  options: Option[];
  values: string[];
  onToggle: (optionId: string) => void;
}) {
  const listRef = useRef<HTMLDivElement>(null);
  const [scrollbar, setScrollbar] = useState({ visible: false, offset: 0, size: 0 });

  function updateScrollbar() {
    const list = listRef.current;
    if (!list) return;
    const maxScroll = list.scrollHeight - list.clientHeight;
    if (maxScroll <= 1) {
      setScrollbar((current) => current.visible ? { visible: false, offset: 0, size: 0 } : current);
      return;
    }
    const size = Math.max(18, (list.clientHeight / list.scrollHeight) * list.clientHeight);
    const offset = (list.scrollTop / maxScroll) * (list.clientHeight - size);
    setScrollbar({ visible: true, offset, size });
  }

  useEffect(() => {
    updateScrollbar();
    const list = listRef.current;
    if (!list || typeof ResizeObserver === "undefined") return undefined;
    const observer = new ResizeObserver(updateScrollbar);
    observer.observe(list);
    return () => observer.disconnect();
  }, [options]);

  return (
    <div className="users-multi-select-shell">
      <div ref={listRef} className="users-multi-select" role="group" aria-label={label} onScroll={updateScrollbar}>
        {options.map((option) => (
          <label className="users-multi-option" key={option.id}>
            <input
              type="checkbox"
              checked={values.includes(option.id)}
              onChange={() => onToggle(option.id)}
            />
            <span title={option.name}>{option.name}</span>
          </label>
        ))}
      </div>
      {scrollbar.visible ? (
        <span className="users-multi-scrollbar" aria-hidden="true">
          <span style={{ height: `${scrollbar.size}px`, transform: `translateY(${scrollbar.offset}px)` }} />
        </span>
      ) : null}
    </div>
  );
}

export { UsersToolbar };
