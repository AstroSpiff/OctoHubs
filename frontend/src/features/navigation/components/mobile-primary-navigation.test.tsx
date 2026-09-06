// @vitest-environment jsdom

import { act } from "react";
import { createRoot } from "react-dom/client";
import { MemoryRouter, useLocation } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import { MobilePrimaryNavigation } from "@/features/navigation/components/mobile-primary-navigation";

declare global {
  var IS_REACT_ACT_ENVIRONMENT: boolean | undefined;
}

describe("MobilePrimaryNavigation", () => {
  let container: HTMLDivElement;
  let root: ReturnType<typeof createRoot>;

  beforeEach(() => {
    globalThis.IS_REACT_ACT_ENVIRONMENT = true;
    window.localStorage.clear();
    container = document.createElement("div");
    document.body.append(container);
    root = createRoot(container);
  });

  afterEach(() => {
    act(() => root.unmount());
    container.remove();
    globalThis.IS_REACT_ACT_ENVIRONMENT = undefined;
  });

  it("does not suppress navigation after dismissing a secondary menu", async () => {
    await act(async () => {
      root.render(
        <MemoryRouter initialEntries={["/collections"]}>
          <NavigationHarness />
        </MemoryRouter>,
      );
    });
    const research = container.querySelector<HTMLAnchorElement>('a[href="/research/independent"]');
    act(() => {
      research?.dispatchEvent(new MouseEvent("contextmenu", { bubbles: true, cancelable: true }));
    });
    expect(container.querySelector('[role="dialog"]')).not.toBeNull();

    act(() => {
      container.querySelector<HTMLButtonElement>('[aria-label="Chiudi menu secondario"]')?.click();
    });
    expect(container.querySelector('[role="dialog"]')).toBeNull();

    act(() => research?.click());
    expect(container.querySelector('[data-location]')?.textContent).toBe("/research/independent");
  });
});

function NavigationHarness() {
  const location = useLocation();
  return (
    <>
      <MobilePrimaryNavigation pathname={location.pathname} />
      <output data-location>{location.pathname}</output>
    </>
  );
}
