import { renderToStaticMarkup } from "react-dom/server";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";

import { EmbyWorkspaceTabs } from "@/features/emby-navigation/components/emby-workspace-tabs";

describe("EmbyWorkspaceTabs", () => {
  it("keeps Event Bridge exclusively under Configuration", () => {
    const markup = renderToStaticMarkup(
      <MemoryRouter initialEntries={["/emby-live"]}>
        <EmbyWorkspaceTabs />
      </MemoryRouter>,
    );

    expect(markup).not.toContain('href="/event-bridge"');
    expect(markup).not.toContain("Event Bridge");
    expect(markup).not.toContain('href="/operations"');
    expect(markup).toContain('href="/emby-live"');
    expect(markup).toContain("workspace-tabs");
  });

  it("uses the same Italian stream-statistics label as the destination page", () => {
    const markup = renderToStaticMarkup(
      <MemoryRouter initialEntries={["/stream-stats"]}>
        <EmbyWorkspaceTabs />
      </MemoryRouter>,
    );

    expect(markup).toContain('href="/stream-stats"');
    expect(markup).toContain("Statistiche stream");
  });

  it("keeps the top navigation rendered when the desktop preference is the nested submenu", () => {
    const markup = renderToStaticMarkup(
      <MemoryRouter initialEntries={["/emby-live"]}>
        <EmbyWorkspaceTabs variant="sidebar" />
      </MemoryRouter>,
    );

    expect(markup).toContain("emby-workspace-tabs--sidebar");
    expect(markup).toContain('href="/emby-live"');
  });
});
