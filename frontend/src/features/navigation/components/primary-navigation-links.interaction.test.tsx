// @vitest-environment jsdom

import { act } from "react";
import { createRoot } from "react-dom/client";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/features/navigation/use-persisted-tab-order", () => ({
  usePersistedTabOrder: ({ tabs }: { tabs: Array<{ id: string }> }) => ({
    order: tabs.map((tab) => tab.id),
    draggingId: null,
    interaction: () => ({
      draggable: true,
      onDragEnd: () => undefined,
      onDragOver: () => undefined,
      onDragStart: () => undefined,
      onDrop: () => undefined,
      onKeyDown: () => false,
    }),
  }),
}));

import { PrimaryNavigationLinks } from "@/features/navigation/components/primary-navigation-links";

declare global {
  var IS_REACT_ACT_ENVIRONMENT: boolean | undefined;
}

describe("PrimaryNavigationLinks top submenu", () => {
  let container: HTMLDivElement;
  let root: ReturnType<typeof createRoot>;

  beforeEach(() => {
    globalThis.IS_REACT_ACT_ENVIRONMENT = true;
    container = document.createElement("div");
    document.body.append(container);
    root = createRoot(container);
    act(() => {
      root.render(
        <MemoryRouter initialEntries={["/research/independent"]}>
          <PrimaryNavigationLinks pathname="/research/independent" variant="top" showSecondaryMenu />
        </MemoryRouter>,
      );
    });
  });

  afterEach(() => {
    act(() => root.unmount());
    container.remove();
    globalThis.IS_REACT_ACT_ENVIRONMENT = undefined;
  });

  it("opens only while its primary item is hovered and closes when it is left", () => {
    const researchItem = Array.from(container.querySelectorAll(".navigation-item"))
      .find((item) => item.textContent?.includes("Ricerca"));

    expect(researchItem).toBeTruthy();
    expect(container.querySelector(".navigation-submenu--top")).toBeNull();

    act(() => {
      researchItem?.dispatchEvent(new MouseEvent("mouseover", { bubbles: true }));
    });
    expect(container.querySelector(".navigation-submenu--top")).not.toBeNull();

    act(() => {
      researchItem?.dispatchEvent(new MouseEvent("mouseout", { bubbles: true, relatedTarget: document.body }));
    });
    expect(container.querySelector(".navigation-submenu--top")).toBeNull();
  });
});
