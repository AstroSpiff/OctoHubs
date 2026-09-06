import { renderToStaticMarkup } from "react-dom/server";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";

import { PrimaryNavigationLinks } from "@/features/navigation/components/primary-navigation-links";

describe("PrimaryNavigationLinks", () => {
  it("expands the Emby destinations directly below the active sidebar item", () => {
    const markup = renderToStaticMarkup(
      <MemoryRouter initialEntries={["/users"]}>
        <PrimaryNavigationLinks pathname="/users" variant="sidebar" showSecondaryMenu />
      </MemoryRouter>,
    );

    expect(markup).toContain("navigation-submenu--sidebar");
    expect(markup).toContain("navigation-reorder-grip");
    expect(markup).toContain('draggable="true"');
    expect(markup).toContain('aria-live="polite"');
    expect(markup).toContain('href="/users"');
    expect(markup).toContain("Statistiche stream");
  });

  it("keeps the submenu out of the page layout when the tab mode is used", () => {
    const markup = renderToStaticMarkup(
      <MemoryRouter initialEntries={["/users"]}>
        <PrimaryNavigationLinks pathname="/users" variant="sidebar" />
      </MemoryRouter>,
    );

    expect(markup).not.toContain("navigation-submenu--sidebar");
  });

  it("expands Research destinations below the active sidebar item", () => {
    const markup = renderToStaticMarkup(
      <MemoryRouter initialEntries={["/research/rules"]}>
        <PrimaryNavigationLinks pathname="/research/rules" variant="sidebar" showSecondaryMenu />
      </MemoryRouter>,
    );

    expect(markup).toContain('href="/research/independent"');
    expect(markup).toContain('href="/research/rules"');
  });

  it("expands Probe destinations below the active sidebar item", () => {
    const markup = renderToStaticMarkup(
      <MemoryRouter initialEntries={["/probe/libraries"]}>
        <PrimaryNavigationLinks pathname="/probe/libraries" variant="sidebar" showSecondaryMenu />
      </MemoryRouter>,
    );

    expect(markup).toContain('href="/probe/recent"');
    expect(markup).toContain('href="/probe/libraries"');
  });
});
