import { Search } from "@/components/ui/icons";

import {
  WorkspaceToolbar,
  WorkspaceToolbarField,
  WorkspaceToolbarGroup,
  WorkspaceToolbarRow,
} from "@/components/ui/workspace-toolbar";
import type { LibraryFilters } from "@/features/libraries/types";

type LibrariesToolbarProps = {
  filters: LibraryFilters;
  onChange: (updates: Partial<LibraryFilters>) => void;
};

function LibrariesToolbar({ filters, onChange }: LibrariesToolbarProps) {
  return (
    <WorkspaceToolbar className="libraries-toolbar" aria-label="Filtri librerie">
      <WorkspaceToolbarRow className="libraries-toolbar-row">
        <WorkspaceToolbarGroup className="libraries-filter-group" label="Filtra">
          <WorkspaceToolbarField className="libraries-search" label="Ricerca">
            <span className="workspace-toolbar-search-control">
              <Search size={16} aria-hidden="true" />
              <input
                aria-label="Cerca gruppi e librerie"
                value={filters.search}
                onChange={(event) => onChange({ search: event.target.value })}
                placeholder="Cerca gruppo, libreria o server..."
              />
            </span>
          </WorkspaceToolbarField>
          <WorkspaceToolbarField className="libraries-type" label="Tipo">
            <select
              className="workspace-toolbar-control"
              value={filters.type}
              onChange={(event) =>
                onChange({ type: event.target.value as LibraryFilters["type"] })
              }
            >
              <option value="all">Tutti i tipi</option>
              <option value="movies">Film</option>
              <option value="tvshows">Serie TV</option>
              <option value="other">Cartelle e altro</option>
            </select>
          </WorkspaceToolbarField>
        </WorkspaceToolbarGroup>
      </WorkspaceToolbarRow>
    </WorkspaceToolbar>
  );
}

export { LibrariesToolbar };
