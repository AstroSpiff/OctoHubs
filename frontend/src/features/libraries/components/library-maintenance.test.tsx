import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { LibraryMaintenance } from "@/features/libraries/components/library-maintenance";

describe("LibraryMaintenance", () => {
  it("shows the configured server identity for focused maintenance actions", () => {
    const markup = renderToStaticMarkup(
      <LibraryMaintenance
        servers={[
          {
            id: "green",
            name: "Green",
            url: "https://green.example.test",
            icon: "fa-film",
            icon_style: "regular",
            icon_color: "#8B5CF6",
          },
        ]}
        serversReady
        activeScans={[]}
        activeScansReady
        workflowMode={false}
        onWorkflowModeChange={() => undefined}
        onRetryServers={() => undefined}
        onRetryActiveScans={() => undefined}
        onRun={() => undefined}
      />,
    );

    expect(markup).toContain("https://green.example.test");
    expect(markup).toContain('data-prefix="fas"');
  });

  it("blocks new maintenance requests while a workflow is active", () => {
    const markup = renderToStaticMarkup(
      <LibraryMaintenance
        servers={[{ id: "green", name: "Green" }]}
        serversReady
        activeScans={[]}
        activeScansReady
        workflowMode
        workflowBusy
        onWorkflowModeChange={() => undefined}
        onRetryServers={() => undefined}
        onRetryActiveScans={() => undefined}
        onRun={() => undefined}
      />,
    );

    expect(markup).toContain("Un workflow e&#x27; gia&#x27; in corso");
    expect(markup).toContain("Workflow in corso...");
    expect(markup.match(/<button[^>]*\sdisabled(?:=|\s|>)/g)).toHaveLength(4);
  });

  it("does not claim empty snapshots or enable actions while maintenance data is unresolved", () => {
    const markup = renderToStaticMarkup(
      <LibraryMaintenance
        servers={[]}
        serversReady={false}
        activeScans={[]}
        activeScansReady={false}
        workflowMode={false}
        onWorkflowModeChange={() => undefined}
        onRetryServers={() => undefined}
        onRetryActiveScans={() => undefined}
        onRun={() => undefined}
      />,
    );

    expect(markup).toContain("Caricamento server disponibili");
    expect(markup).toContain("Caricamento attività Emby");
    expect(markup).not.toContain("Nessun server Emby abilitato");
    expect(markup).not.toContain("Nessuna scansione Emby in corso");
    expect(markup.match(/<button[^>]*\sdisabled(?:=|\s|>)/g)).toHaveLength(2);
  });

  it("keeps a stale successful snapshot visible beside its refresh error", () => {
    const markup = renderToStaticMarkup(
      <LibraryMaintenance
        servers={[{ id: "green", name: "Green" }]}
        serversReady
        serversError={new Error("Refresh server non riuscito")}
        activeScans={[]}
        activeScansReady
        workflowMode={false}
        onWorkflowModeChange={() => undefined}
        onRetryServers={() => undefined}
        onRetryActiveScans={() => undefined}
        onRun={() => undefined}
      />,
    );

    expect(markup).toContain("Refresh server non riuscito");
    expect(markup).toContain("Green");
  });
});
