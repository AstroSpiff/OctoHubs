import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { WorkspaceStatusOverview } from "@/components/ui/workspace-status-overview";

describe("WorkspaceStatusOverview", () => {
  it("keeps the operational status and metrics in one responsive overview", () => {
    const markup = renderToStaticMarkup(
      <WorkspaceStatusOverview
        columns={3}
        description="Ultimo aggiornamento"
        icon={<span>Icona</span>}
        iconTone="ok"
        metrics={[
          { label: "Server", value: 4 },
          { label: "Stream", value: 2 },
        ]}
        status={<span>Connesso</span>}
        title="Stato in diretta"
      />,
    );

    expect(markup).toContain("workspace-status-overview");
    expect(markup).toContain("--workspace-status-overview-columns:3");
    expect(markup).toContain("Connesso");
    expect(markup).toContain("Stream");
  });
});
