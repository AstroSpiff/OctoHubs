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
        activeScans={[]}
        workflowMode={false}
        onWorkflowModeChange={() => undefined}
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
        activeScans={[]}
        workflowMode
        workflowBusy
        onWorkflowModeChange={() => undefined}
        onRun={() => undefined}
      />,
    );

    expect(markup).toContain("Un workflow e&#x27; gia&#x27; in corso");
    expect(markup).toContain("Workflow in corso...");
    expect(markup.match(/<button[^>]*\sdisabled(?:=|\s|>)/g)).toHaveLength(4);
  });
});
