// @vitest-environment jsdom

import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { LatestDataVerify } from "@/features/emby-latest/components/latest-data-verify";
import type { LatestItem } from "@/features/emby-latest/types";

declare global {
  var IS_REACT_ACT_ENVIRONMENT: boolean | undefined;
}

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((complete) => { resolve = complete; });
  return { promise, resolve };
}

describe("LatestDataVerify snapshot ownership", () => {
  let container: HTMLDivElement;
  let root: ReturnType<typeof createRoot>;

  beforeEach(() => {
    globalThis.IS_REACT_ACT_ENVIRONMENT = true;
    container = document.createElement("div");
    document.body.appendChild(container);
    root = createRoot(container);
  });

  afterEach(() => {
    act(() => root.unmount());
    container.remove();
    globalThis.IS_REACT_ACT_ENVIRONMENT = undefined;
  });

  it("ignores enrichment from an older snapshot and resets on reopen", async () => {
    const oldResult = deferred<LatestItem>();
    const resetError = vi.fn();
    const servers = [{ id: "green", name: "Green" }];
    const noSeries: LatestItem[] = [];
    const first = [{ item_id: "movie-1", server_id: "green", title: "Old" }];
    const replacement = [{ item_id: "movie-1", server_id: "green", title: "New" }];
    const render = (open: boolean, movies: LatestItem[]) => {
      root.render(
        <LatestDataVerify
          open={open}
          servers={servers}
          movies={movies}
          series={noSeries}
          enriching={false}
          onClose={() => undefined}
          onEnrich={() => oldResult.promise}
          onResetError={resetError}
        />,
      );
    };

    await act(async () => render(true, first));
    changeSelect(container, "Server", "green");
    changeSelect(container, "Contenuto", "green-movie-1");
    act(() => buttonWithText(container, "Aggiorna dati").click());

    await act(async () => render(true, replacement));
    await act(async () => {
      oldResult.resolve({
        item_id: "movie-1",
        server_id: "green",
        title: "Old enriched",
        tmdb_id: 123,
      });
      await oldResult.promise;
    });

    expect(container.querySelector(".latest-verification-report")).toBeNull();
    await act(async () => render(false, replacement));
    await act(async () => render(true, replacement));
    expect(selectWithLabel(container, "Server").value).toBe("");
    expect(selectWithLabel(container, "Contenuto").value).toBe("");
  });
});

function selectWithLabel(container: HTMLElement, label: string) {
  const element = [...container.querySelectorAll("label")]
    .find((candidate) => candidate.textContent?.includes(label))
    ?.querySelector<HTMLSelectElement>("select");
  if (!element) throw new Error(`Select not found: ${label}`);
  return element;
}

function changeSelect(container: HTMLElement, label: string, value: string) {
  const select = selectWithLabel(container, label);
  act(() => {
    select.value = value;
    select.dispatchEvent(new Event("change", { bubbles: true }));
  });
}

function buttonWithText(container: HTMLElement, text: string) {
  const button = [...container.querySelectorAll<HTMLButtonElement>("button")]
    .find((candidate) => candidate.textContent?.includes(text));
  if (!button) throw new Error(`Button not found: ${text}`);
  return button;
}
