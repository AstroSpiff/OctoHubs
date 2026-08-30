import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { WorkspaceCardHeading } from "@/components/ui/workspace-card-heading";

describe("WorkspaceCardHeading", () => {
  it("keeps card titles, contextual help, counts, and actions in one header", () => {
    const markup = renderToStaticMarkup(
      <WorkspaceCardHeading
        actions={<button type="button">Aggiorna</button>}
        context="Cronologia"
        count={4}
        leading={<span>Icona</span>}
        title="Ultime riproduzioni"
      />,
    );

    expect(markup).toContain("workspace-card-heading");
    expect(markup).toContain('title="Cronologia"');
    expect(markup).toContain('workspace-card-heading-count">4');
    expect(markup).toContain("Aggiorna");
  });
});
