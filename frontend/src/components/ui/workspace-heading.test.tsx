import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { Circle } from "@/components/ui/icons";

import { WorkspaceHeading } from "@/components/ui/workspace-heading";

describe("WorkspaceHeading", () => {
  it("uses one page title or one section title without changing its layout contract", () => {
    const pageMarkup = renderToStaticMarkup(
      <WorkspaceHeading
        actionsClassName="example-actions"
        context="Area"
        title="Titolo pagina"
        description="Descrizione della pagina"
        actions={<button type="button">Azione</button>}
      />,
    );
    const sectionMarkup = renderToStaticMarkup(
      <WorkspaceHeading
        level="section"
        leading={<Circle aria-hidden="true" />}
        title="Titolo sezione"
      />,
    );
    const subsectionMarkup = renderToStaticMarkup(
      <WorkspaceHeading level="subsection" title="Titolo sottosezione" />,
    );

    expect(pageMarkup).toContain(">Titolo pagina</h1>");
    expect(pageMarkup).toContain('title="Area"');
    expect(pageMarkup).not.toContain("eyebrow");
    expect(pageMarkup).toContain("workspace-heading-description");
    expect(pageMarkup).toContain("workspace-heading-actions example-actions");
    expect(sectionMarkup).toContain("<h2>Titolo sezione</h2>");
    expect(sectionMarkup).toContain("workspace-heading-leading");
    expect(subsectionMarkup).toContain("<h3>Titolo sottosezione</h3>");
  });
});
