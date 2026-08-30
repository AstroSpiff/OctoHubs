import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { WorkspaceMetricGrid } from "@/components/ui/workspace-metric-grid";

describe("WorkspaceMetricGrid", () => {
  it("renders compact metrics with their semantic tones", () => {
    const markup = renderToStaticMarkup(
      <WorkspaceMetricGrid
        metrics={[
          { icon: <span>1</span>, label: "Attive", tone: "ok", value: 3 },
          { icon: <span>2</span>, label: "Avvisi", tone: "warning", value: 1 },
        ]}
      />,
    );

    expect(markup).toContain("workspace-metric-grid");
    expect(markup).toContain("workspace-metric-icon is-ok");
    expect(markup).toContain("Avvisi");
  });
});
