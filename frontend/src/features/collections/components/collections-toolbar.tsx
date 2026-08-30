import { Search } from "@/components/ui/icons";

import {
  WorkspaceToolbar,
  WorkspaceToolbarField,
  WorkspaceToolbarGroup,
  WorkspaceToolbarRow,
} from "@/components/ui/workspace-toolbar";
import type { CollectionsFilters } from "@/features/collections/types";

type CollectionsToolbarProps = {
  filters: CollectionsFilters;
  onChange: (changes: Partial<CollectionsFilters>) => void;
};

function CollectionsToolbar({ filters, onChange }: CollectionsToolbarProps) {
  return (
    <WorkspaceToolbar className="collections-toolbar" aria-label="Filtri collezioni">
      <WorkspaceToolbarRow className="collections-toolbar-row">
        <WorkspaceToolbarGroup className="collections-filter-group" label="Filtra">
          <WorkspaceToolbarField className="collections-search" label="Ricerca">
            <span className="workspace-toolbar-search-control">
              <Search size={16} aria-hidden="true" />
              <input
                value={filters.search}
                onChange={(event) => onChange({ search: event.target.value })}
                placeholder="Cerca collezione, fonte o server..."
              />
            </span>
          </WorkspaceToolbarField>
          <WorkspaceToolbarField className="collections-select" label="Stato">
            <select
              className="workspace-toolbar-control"
              value={filters.status}
              onChange={(event) =>
                onChange({ status: event.target.value as CollectionsFilters["status"] })
              }
            >
              <option value="all">Tutte</option>
              <option value="enabled">Attive</option>
              <option value="disabled">Disabilitate</option>
              <option value="attention">Da verificare</option>
            </select>
          </WorkspaceToolbarField>
        </WorkspaceToolbarGroup>
        <WorkspaceToolbarField className="collections-select" label="Ordina">
          <select
            className="workspace-toolbar-control"
            value={filters.sort}
            onChange={(event) =>
              onChange({ sort: event.target.value as CollectionsFilters["sort"] })
            }
          >
            <option value="name">Nome</option>
            <option value="sync">Ultima sincronizzazione</option>
            <option value="source">Fonte</option>
          </select>
        </WorkspaceToolbarField>
      </WorkspaceToolbarRow>
    </WorkspaceToolbar>
  );
}

export { CollectionsToolbar };
