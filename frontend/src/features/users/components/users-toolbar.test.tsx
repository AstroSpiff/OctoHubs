import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { WorkspaceCapabilitiesProvider } from "@/features/session/workspace-capabilities";
import { UsersToolbar } from "@/features/users/components/users-toolbar";

const props = {
  data: { groups: [], servers: [{ id: "green", name: "Green" }] },
  iconProfiles: [],
  filters: {
    search: "",
    groupType: "all" as const,
    serverIds: ["green"],
    statuses: [],
    iconProfileIds: [],
    sort: "name_asc_server_asc" as const,
  },
  selection: {
    visibleCount: 1,
    selectedVisibleCount: 0,
    leaderCount: 1,
    selectedLeaderCount: 0,
  },
  refreshing: false,
  onChange: () => undefined,
  onSelectAll: () => undefined,
  onSelectLeaders: () => undefined,
  onDeselect: () => undefined,
  onCreate: () => undefined,
  onRefresh: () => undefined,
};

describe("UsersToolbar", () => {
  it("keeps search next to quick selection and stacks type with order after the multiselect filters", () => {
    const markup = renderToStaticMarkup(
      <UsersToolbar
        {...props}
      />,
    );

    expect(markup.indexOf("users-selection-group")).toBeLessThan(
      markup.indexOf("users-search-group"),
    );
    expect(markup.indexOf("users-search-group")).toBeLessThan(
      markup.indexOf("users-actions-group"),
    );
    expect(markup).toContain("Filtri e ordinamento");
    expect(markup).toContain('<details class="users-filter-group">');
    expect(markup).not.toContain('<details class="users-filter-group" open="">');
    expect(markup).toContain("users-filter-summary");
    expect(markup.indexOf('aria-label="Tipo"')).toBeLessThan(
      markup.indexOf('aria-label="Ordina"'),
    );
    expect(markup.indexOf('aria-label="Profilo icona"')).toBeLessThan(
      markup.indexOf('aria-label="Tipo"'),
    );
    expect(markup).toContain('aria-label="Ordina"');
    expect(markup).toContain("users-filter-select-stack");
    expect(markup).toContain('type="checkbox"');
    expect(markup).not.toContain('multiple=""');
    expect(markup).toContain('aria-label="Azzera filtro Server"');
    expect(markup).not.toContain("users-sort-controls");
  });

  it("hides bulk selection and create controls from viewers while retaining read actions", () => {
    const markup = renderToStaticMarkup(
      <WorkspaceCapabilitiesProvider canMutate={false}>
        <UsersToolbar {...props} />
      </WorkspaceCapabilitiesProvider>,
    );

    expect(markup).not.toContain("users-selection-group");
    expect(markup).not.toContain("Crea utente");
    expect(markup).toContain("users-toolbar-primary--read-only");
    expect(markup).toContain("Cerca utenti o gruppi");
    expect(markup).toContain("Aggiorna elenco utenti");
  });
});
