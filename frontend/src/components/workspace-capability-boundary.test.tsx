import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { WorkspaceCapabilityBoundary } from "@/components/app-shell";
import { Button } from "@/components/ui/button";
import { CollectionsToolbar } from "@/features/collections/components/collections-toolbar";
import { StreamStatsFilters } from "@/features/stream-stats/components/stream-stats-filters";


describe("WorkspaceCapabilityBoundary", () => {
  it("keeps read-only controls enabled and hides write actions for viewers", () => {
    const markup = renderToStaticMarkup(
      <WorkspaceCapabilityBoundary accessState="viewer">
        <input name="filter" />
        <Button type="button">Aggiorna</Button>
        <Button type="button" requiresWriteAccess>Salva</Button>
      </WorkspaceCapabilityBoundary>,
    );

    expect(markup).not.toContain("<fieldset");
    expect(markup).not.toContain("disabled=\"\"");
    expect(markup).toContain("Aggiorna");
    expect(markup).not.toContain("Salva");
    expect(markup).toContain("Account in sola lettura");
  });

  it("shows write actions to users with mutation access", () => {
    const markup = renderToStaticMarkup(
      <WorkspaceCapabilityBoundary accessState="editor">
        <Button type="button" requiresWriteAccess>Salva</Button>
      </WorkspaceCapabilityBoundary>,
    );

    expect(markup).toContain("Salva");
    expect(markup).not.toContain("Account in sola lettura");
  });

  it("keeps the real collection and stream filters available to viewers", () => {
    const markup = renderToStaticMarkup(
      <WorkspaceCapabilityBoundary accessState="viewer">
        <CollectionsToolbar
          filters={{ search: "", status: "all", sort: "name" }}
          onChange={() => undefined}
        />
        <StreamStatsFilters
          filters={{ period: "24h", server_id: "", user: "", client: "", issues_only: false, sort: "issues_desc", limit: 50 }}
          facets={{ servers: [], users: [], clients: [] }}
          onChange={() => undefined}
          onReset={() => undefined}
        />
      </WorkspaceCapabilityBoundary>,
    );

    expect(markup).toContain("Cerca collezione, fonte o server...");
    expect(markup).toContain("Ripristina filtri");
    expect(markup).not.toContain("disabled=\"\"");
  });

  it("fails closed while the session is loading", () => {
    const markup = renderToStaticMarkup(
      <WorkspaceCapabilityBoundary accessState="loading">
        <Button type="button" requiresWriteAccess>Elimina</Button>
      </WorkspaceCapabilityBoundary>,
    );

    expect(markup).toContain("Verifica della sessione in corso");
    expect(markup).not.toContain("Elimina");
  });

  it("fails closed and offers retry when session verification fails", () => {
    const markup = renderToStaticMarkup(
      <WorkspaceCapabilityBoundary accessState="error" onRetry={() => undefined}>
        <Button type="button" requiresWriteAccess>Elimina</Button>
      </WorkspaceCapabilityBoundary>,
    );

    expect(markup).toContain("Impossibile verificare i permessi");
    expect(markup).toContain("Riprova");
    expect(markup).not.toContain("Elimina");
  });
});
