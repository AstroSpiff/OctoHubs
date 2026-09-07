// @vitest-environment jsdom

import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { AccountMenu } from "@/components/account-menu";

declare global {
  var IS_REACT_ACT_ENVIRONMENT: boolean | undefined;
}

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

describe("AccountMenu responsive lifecycle", () => {
  let container: HTMLDivElement;
  let root: ReturnType<typeof createRoot>;

  beforeEach(() => {
    globalThis.IS_REACT_ACT_ENVIRONMENT = true;
    container = document.createElement("div");
    document.body.append(container);
    root = createRoot(container);
  });

  afterEach(() => {
    act(() => root.unmount());
    container.remove();
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
    globalThis.IS_REACT_ACT_ENVIRONMENT = undefined;
  });

  it("closes a mobile sheet and focuses the desktop account control", async () => {
    const query = mutableMediaQuery(true);
    vi.stubGlobal("matchMedia", vi.fn(() => query));

    await act(async () => {
      root.render(
        <AccountMenu
          roleLabel="Amministratore"
          theme="light"
          username="roy"
          onOpenPreferences={() => undefined}
          onToggleTheme={() => undefined}
        />,
      );
    });
    act(() => container.querySelector<HTMLButtonElement>('[aria-haspopup="dialog"]')?.click());
    expect(document.querySelector('.account-menu-sheet[role="dialog"]')).not.toBeNull();

    act(() => query.setMatches(false));

    expect(document.querySelector('.account-menu-sheet[role="dialog"]')).toBeNull();
    expect(document.activeElement).toBe(container.querySelector("summary"));
  });
});
