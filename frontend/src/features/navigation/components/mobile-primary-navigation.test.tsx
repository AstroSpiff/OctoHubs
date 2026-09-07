// @vitest-environment jsdom

import { act } from "react";
import { createRoot } from "react-dom/client";
import { MemoryRouter, useLocation } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { MobilePrimaryNavigation } from "@/features/navigation/components/mobile-primary-navigation";

declare global {
  var IS_REACT_ACT_ENVIRONMENT: boolean | undefined;
}

describe("MobilePrimaryNavigation", () => {
  let container: HTMLDivElement;
  let root: ReturnType<typeof createRoot>;
  let mediaQuery: ReturnType<typeof mutableMediaQuery>;

  beforeEach(() => {
    globalThis.IS_REACT_ACT_ENVIRONMENT = true;
    window.localStorage.clear();
    container = document.createElement("div");
    document.body.append(container);
    root = createRoot(container);
    mediaQuery = mutableMediaQuery(true);
    vi.stubGlobal("matchMedia", vi.fn(() => mediaQuery));
  });

  afterEach(() => {
    act(() => root.unmount());
    container.remove();
    vi.useRealTimers();
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
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

  it("closes an open mobile sheet and restores focus to desktop navigation", async () => {
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

    const desktopNavigation = document.createElement("nav");
    desktopNavigation.className = "app-navigation";
    const desktopResearch = document.createElement("a");
    desktopResearch.dataset.primaryNavigationId = "research";
    desktopResearch.tabIndex = 0;
    desktopNavigation.append(desktopResearch);
    document.body.append(desktopNavigation);

    await act(async () => {
      mediaQuery.setMatches(false);
    });

    expect(container.querySelector('[role="dialog"]')).toBeNull();
    await vi.waitFor(() => expect(document.activeElement).toBe(desktopResearch));
    desktopNavigation.remove();
  });

  it("does not carry context-menu click suppression across breakpoint changes", async () => {
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

    await act(async () => mediaQuery.setMatches(false));
    await act(async () => mediaQuery.setMatches(true));
    act(() => research?.click());

    expect(container.querySelector('[data-location]')?.textContent).toBe("/research/independent");
  });

  it("cancels a pending long press when leaving the mobile breakpoint", async () => {
    vi.useFakeTimers();
    await act(async () => {
      root.render(
        <MemoryRouter initialEntries={["/collections"]}>
          <NavigationHarness />
        </MemoryRouter>,
      );
    });
    const research = container.querySelector<HTMLAnchorElement>('a[href="/research/independent"]');
    act(() => {
      research?.dispatchEvent(new Event("pointerdown", { bubbles: true, cancelable: true }));
    });

    await act(async () => mediaQuery.setMatches(false));
    act(() => vi.advanceTimersByTime(600));
    await act(async () => mediaQuery.setMatches(true));

    expect(container.querySelector('[role="dialog"]')).toBeNull();
  });

  it("cancels desktop focus restoration when mobile mode re-enters before the frame", async () => {
    const frames = new Map<number, FrameRequestCallback>();
    let nextFrame = 1;
    vi.stubGlobal("requestAnimationFrame", vi.fn((callback: FrameRequestCallback) => {
      const frame = nextFrame++;
      frames.set(frame, callback);
      return frame;
    }));
    vi.stubGlobal("cancelAnimationFrame", vi.fn((frame: number) => {
      frames.delete(frame);
    }));
    await act(async () => {
      root.render(
        <MemoryRouter initialEntries={["/collections"]}>
          <NavigationHarness />
        </MemoryRouter>,
      );
    });
    const research = container.querySelector<HTMLAnchorElement>('a[href="/research/independent"]');
    act(() => research?.dispatchEvent(new MouseEvent("contextmenu", { bubbles: true, cancelable: true })));

    const desktopNavigation = document.createElement("nav");
    desktopNavigation.className = "app-navigation";
    const desktopResearch = document.createElement("a");
    desktopResearch.dataset.primaryNavigationId = "research";
    desktopResearch.tabIndex = 0;
    desktopNavigation.append(desktopResearch);
    document.body.append(desktopNavigation);
    research?.focus();

    await act(async () => mediaQuery.setMatches(false));
    expect(frames.size).toBe(1);
    await act(async () => mediaQuery.setMatches(true));
    frames.forEach((callback) => callback(performance.now()));

    expect(frames.size).toBe(0);
    expect(document.activeElement).not.toBe(desktopResearch);
    desktopNavigation.remove();
  });
});

function mutableMediaQuery(initialMatches: boolean) {
  const listeners = new Set<(event: MediaQueryListEvent) => void>();
  const query = {
    matches: initialMatches,
    media: "(max-width: 899px)",
    onchange: null,
    addEventListener: (_type: string, listener: (event: MediaQueryListEvent) => void) => listeners.add(listener),
    removeEventListener: (_type: string, listener: (event: MediaQueryListEvent) => void) => listeners.delete(listener),
    addListener: () => undefined,
    removeListener: () => undefined,
    dispatchEvent: () => true,
    setMatches(matches: boolean) {
      query.matches = matches;
      listeners.forEach((listener) => listener({ matches } as MediaQueryListEvent));
    },
  };
  return query;
}

function NavigationHarness() {
  const location = useLocation();
  return (
    <>
      <MobilePrimaryNavigation pathname={location.pathname} />
      <output data-location>{location.pathname}</output>
    </>
  );
}
