import { renderToStaticMarkup } from "react-dom/server";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";

import { ProbeScopeTabs } from "@/features/probe/components/probe-scope-tabs";

describe("ProbeScopeTabs", () => {
  it("mantiene il riordino persistente delle tab della UI legacy", () => {
    const markup = renderToStaticMarkup(
      <MemoryRouter><ProbeScopeTabs value="recent">Contenuto Probe</ProbeScopeTabs></MemoryRouter>,
    );

    expect(markup).toContain("Ultimi aggiunti");
    expect(markup).toContain("Librerie");
    expect(markup).toContain('draggable="true"');
    expect(markup).toContain("tab-reorder-grip");
    expect(markup).toContain("workspace-tabs");
    expect(markup).toContain("workspace-tab-panel");
    expect(markup).toContain("Contenuto Probe");
  });

  it("keeps the scope tabs in the DOM when the desktop sidebar submenu is selected", () => {
    const markup = renderToStaticMarkup(
      <MemoryRouter><ProbeScopeTabs value="recent" variant="sidebar" /></MemoryRouter>,
    );

    expect(markup).toContain("probe-scope-tabs--sidebar");
  });
});
