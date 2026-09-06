// @vitest-environment jsdom

import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import { RequestSeasonStatus } from "@/features/research/components/request-season-status";

declare global {
  var IS_REACT_ACT_ENVIRONMENT: boolean | undefined;
}

describe("RequestSeasonStatus", () => {
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
    globalThis.IS_REACT_ACT_ENVIRONMENT = undefined;
  });

  it("keeps the selected season stable across reorder and reconciles removals", async () => {
    const seasons = [season(1), season(2), season(3)];
    await render(seasons);
    act(() => container.querySelectorAll<HTMLButtonElement>('[role="tab"]')[2].click());

    await render([season(3), season(1)]);
    expect(container.querySelector('[role="tab"][aria-selected="true"]')?.textContent).toContain("S03");
    expect(container.querySelector<HTMLElement>('[role="tabpanel"]')?.textContent).toContain("E03");

    await render([season(1)]);
    const panel = container.querySelector<HTMLElement>('[role="tabpanel"]');
    expect(panel?.id).toMatch(/panel-0$/);
    expect(panel?.getAttribute("aria-labelledby")).toMatch(/tab-0$/);
    expect(document.getElementById(panel?.getAttribute("aria-labelledby") || "")).not.toBeNull();
    expect(panel?.textContent).toContain("E01");
  });

  async function render(seasons: Array<Record<string, unknown>>) {
    await act(async () => {
      root.render(<RequestSeasonStatus seasons={seasons} />);
    });
  }
});

function season(value: number) {
  return {
    season: value,
    status: "pending",
    episodes: [{ episode: value, status: "pending" }],
  };
}
