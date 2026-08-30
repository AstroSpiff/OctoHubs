// @vitest-environment jsdom

import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { SearchResultTermMenu } from "@/features/research/components/search-result-term-menu";

declare global {
  var IS_REACT_ACT_ENVIRONMENT: boolean | undefined;
}

describe("SearchResultTermMenu", () => {
  let container: HTMLDivElement;
  let root: ReturnType<typeof createRoot>;

  beforeEach(() => {
    globalThis.IS_REACT_ACT_ENVIRONMENT = true;
    container = document.createElement("div");
    document.body.append(container);
    root = createRoot(container);
    vi.spyOn(window, "requestAnimationFrame").mockImplementation(
      (callback) => {
        callback(0);
        return 1;
      },
    );
    vi.spyOn(window, "cancelAnimationFrame").mockImplementation(() => undefined);
  });

  afterEach(() => {
    act(() => root.unmount());
    container.remove();
    vi.restoreAllMocks();
    globalThis.IS_REACT_ACT_ENVIRONMENT = undefined;
  });

  it("focuses the first action and lets keyboard users move through the menu", () => {
    act(() => {
      root.render(
        <SearchResultTermMenu
          menu={{ term: "1080p", x: 10, y: 10 }}
          onAddTerm={vi.fn(async () => "Aggiornato")}
          onNotice={() => undefined}
          onClose={() => undefined}
        />,
      );
    });

    const items = Array.from(
      container.querySelectorAll<HTMLButtonElement>('[role="menuitem"]'),
    );
    expect(document.activeElement).toBe(items[0]);

    act(() => {
      items[0].dispatchEvent(
        new KeyboardEvent("keydown", { bubbles: true, key: "ArrowDown" }),
      );
    });
    expect(document.activeElement).toBe(items[1]);

    act(() => {
      items[1].dispatchEvent(
        new KeyboardEvent("keydown", { bubbles: true, key: "End" }),
      );
    });
    expect(document.activeElement).toBe(items[2]);

    act(() => {
      items[2].dispatchEvent(
        new KeyboardEvent("keydown", { bubbles: true, key: "ArrowDown" }),
      );
    });
    expect(document.activeElement).toBe(items[0]);
  });
});
