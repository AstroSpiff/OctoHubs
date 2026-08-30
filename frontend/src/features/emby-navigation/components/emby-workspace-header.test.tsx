import { renderToStaticMarkup } from "react-dom/server";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";

import { EmbyWorkspaceHeader } from "@/features/emby-navigation/components/emby-workspace-header";

describe("EmbyWorkspaceHeader", () => {
  it("groups the workspace title, description, and navigation on Emby routes", () => {
    const markup = renderToStaticMarkup(
      <MemoryRouter initialEntries={["/emby-live"]}>
        <EmbyWorkspaceHeader variant="tabs" />
      </MemoryRouter>,
    );

    expect(markup).toContain('id="emby-workspace-title"');
    expect(markup).toContain("Emby Toolkit");
    expect(markup).toContain("protezione della riproduzione");
    expect(markup).not.toContain('href="/event-bridge"');
  });

  it("does not render outside the Emby workspace", () => {
    const markup = renderToStaticMarkup(
      <MemoryRouter initialEntries={["/research"]}>
        <EmbyWorkspaceHeader variant="tabs" />
      </MemoryRouter>,
    );

    expect(markup).toBe("");
  });

  it("keeps a distinct sidebar header mode when the in-page tabs are hidden", () => {
    const markup = renderToStaticMarkup(
      <MemoryRouter initialEntries={["/libraries"]}>
        <EmbyWorkspaceHeader variant="sidebar" />
      </MemoryRouter>,
    );

    expect(markup).toContain("emby-workspace-header--sidebar");
    expect(markup).toContain("emby-workspace-tabs--sidebar");
  });
});
