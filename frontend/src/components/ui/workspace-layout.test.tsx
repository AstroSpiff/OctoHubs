import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { WorkspacePage, WorkspaceSection, WorkspaceTabLayout, WorkspaceTabPanel } from "@/components/ui/workspace-layout";

describe("workspace layout", () => {
  it("provides the common page, section, and unframed tab structure", () => {
    const markup = renderToStaticMarkup(
      <WorkspacePage>
        <WorkspaceSection>
          <WorkspaceTabLayout>
            <WorkspaceTabPanel role="tabpanel">Contenuto</WorkspaceTabPanel>
          </WorkspaceTabLayout>
        </WorkspaceSection>
      </WorkspacePage>,
    );

    expect(markup).toContain("page-layout workspace-page");
    expect(markup).toContain("workspace-section");
    expect(markup).toContain("workspace-tab-layout");
    expect(markup).toContain("workspace-tab-panel");
    expect(markup).not.toContain("workspace-surface");
  });
});
