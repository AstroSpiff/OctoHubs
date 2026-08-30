import { renderToStaticMarkup } from "react-dom/server";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";

import { WorkspaceRouteTabLayout } from "@/features/navigation/components/workspace-route-tab-layout";

describe("WorkspaceRouteTabLayout", () => {
  it("keeps route tabs and their unframed panel in one shared layout", () => {
    const markup = renderToStaticMarkup(
      <MemoryRouter initialEntries={["/one"]}>
        <WorkspaceRouteTabLayout
          activeId="one"
          ariaLabel="Sezioni"
          layoutClassName="example-layout"
          tabsClassName="example-tabs"
          orderPage="example"
          tabs={[
            { id: "one", label: "Uno", to: "/one" },
            { id: "two", label: "Due", to: "/two" },
          ]}
        >
          Contenuto
        </WorkspaceRouteTabLayout>
      </MemoryRouter>,
    );

    expect(markup).toContain("workspace-tab-layout example-layout");
    expect(markup).toContain("workspace-tabs example-tabs");
    expect(markup).toContain("workspace-tab-panel");
    expect(markup).toContain("Contenuto");
  });
});
