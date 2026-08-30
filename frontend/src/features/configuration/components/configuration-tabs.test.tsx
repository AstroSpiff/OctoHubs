import { renderToStaticMarkup } from "react-dom/server";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";

import { ConfigurationTabs } from "@/features/configuration/components/configuration-tabs";

describe("ConfigurationTabs", () => {
  it("keeps the tab list rendered when the desktop preference is the nested submenu", () => {
    const markup = renderToStaticMarkup(
      <MemoryRouter>
        <ConfigurationTabs active="servers" variant="sidebar">
          <div>Contenuto configurazione</div>
        </ConfigurationTabs>
      </MemoryRouter>,
    );

    expect(markup).toContain("configuration-tabs--sidebar");
    expect(markup).toContain("workspace-tabs");
    expect(markup).toContain('aria-label="Sezioni configurazione"');
    expect(markup.indexOf("Stato sistema")).toBeLessThan(markup.indexOf("Server Emby"));
    expect(markup).toContain("Server Emby");
  });

  it("renders the active tab in a semantic panel without a generic visual surface", () => {
    const markup = renderToStaticMarkup(
      <MemoryRouter>
        <ConfigurationTabs active="system-status">
          <div>Stato operativo</div>
        </ConfigurationTabs>
      </MemoryRouter>,
    );

    expect(markup).toContain("workspace-tab-panel");
    expect(markup).not.toContain("configuration-workspace");
  });
});
