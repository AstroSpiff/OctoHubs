import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import {
  WorkspaceToolbar,
  WorkspaceToolbarActions,
  WorkspaceToolbarField,
  WorkspaceToolbarGroup,
  WorkspaceToolbarRow,
} from "@/components/ui/workspace-toolbar";

describe("WorkspaceToolbar", () => {
  it("provides one shared structure for grouped controls and labelled fields", () => {
    const markup = renderToStaticMarkup(
      <WorkspaceToolbar aria-label="Filtri">
        <WorkspaceToolbarRow>
          <WorkspaceToolbarGroup label="Filtra">
            <WorkspaceToolbarField label="Stato">
              <select className="workspace-toolbar-control"><option>Attivo</option></select>
            </WorkspaceToolbarField>
          </WorkspaceToolbarGroup>
          <WorkspaceToolbarActions role="group" aria-label="Azioni">
            <button type="button">Aggiorna</button>
          </WorkspaceToolbarActions>
        </WorkspaceToolbarRow>
      </WorkspaceToolbar>,
    );

    expect(markup).toContain("workspace-toolbar");
    expect(markup).toContain("workspace-toolbar-group-content");
    expect(markup).toContain("workspace-toolbar-label");
    expect(markup).toContain("workspace-toolbar-control");
    expect(markup).toContain('role="group"');
    expect(markup).toContain("workspace-toolbar-actions");
  });

  it("keeps controls and local actions inside the compact toolbar rhythm", () => {
    const markup = renderToStaticMarkup(
      <WorkspaceToolbar>
        <WorkspaceToolbarActions>
          <button type="button">Azione</button>
        </WorkspaceToolbarActions>
      </WorkspaceToolbar>,
    );

    expect(markup).toContain("workspace-toolbar-actions");
  });
});
