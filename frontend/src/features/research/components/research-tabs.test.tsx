import { renderToStaticMarkup } from "react-dom/server";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";

import { ResearchTabs } from "@/features/research/components/research-tabs";

describe("ResearchTabs", () => {
  it("uses the shared workspace-tab presentation", () => {
    const markup = renderToStaticMarkup(
      <MemoryRouter>
        <ResearchTabs active="independent">
          <div>Contenuto ricerca</div>
        </ResearchTabs>
      </MemoryRouter>,
    );

    expect(markup).toContain("workspace-tabs");
    expect(markup).toContain("Ricerca indipendente");
    expect(markup).toContain('aria-label="Sezioni ricerca"');
    expect(markup).toContain('href="/research/independent"');
  });

  it("keeps the tabs rendered when the desktop sidebar submenu is selected", () => {
    const markup = renderToStaticMarkup(
      <MemoryRouter>
        <ResearchTabs active="independent" variant="sidebar">
          <div>Contenuto ricerca</div>
        </ResearchTabs>
      </MemoryRouter>,
    );

    expect(markup).toContain("research-tabs--sidebar");
  });
});
