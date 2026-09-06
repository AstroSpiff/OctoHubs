// @vitest-environment jsdom

import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { SearchResultTable } from "@/features/research/components/search-result-table";
import { WorkspaceCapabilitiesProvider } from "@/features/session/workspace-capabilities";

declare global {
  var IS_REACT_ACT_ENVIRONMENT: boolean | undefined;
}

describe("SearchResultTable term actions", () => {
  let container: HTMLDivElement;
  let root: ReturnType<typeof createRoot>;

  beforeEach(() => {
    globalThis.IS_REACT_ACT_ENVIRONMENT = true;
    container = document.createElement("div");
    document.body.append(container);
    root = createRoot(container);
    vi.spyOn(window, "requestAnimationFrame").mockImplementation((callback) => {
      callback(0);
      return 1;
    });
    vi.spyOn(window, "cancelAnimationFrame").mockImplementation(() => undefined);
  });

  afterEach(() => {
    act(() => root.unmount());
    container.remove();
    vi.restoreAllMocks();
    globalThis.IS_REACT_ACT_ENVIRONMENT = undefined;
  });

  it("offers a keyboard and touch-friendly menu trigger to editors", async () => {
    const onAddTerm = vi.fn(async () => "Regola aggiornata");
    renderTable(true, onAddTerm);

    const trigger = container.querySelector<HTMLButtonElement>(
      '[aria-label="Apri menu termini per Film 1080p"]',
    );
    expect(trigger).not.toBeNull();
    expect(trigger?.getAttribute("aria-haspopup")).toBe("menu");
    expect(trigger?.getAttribute("aria-controls")).toBe("research-result-term-menu");
    expect(trigger?.getAttribute("aria-expanded")).toBe("false");

    act(() => trigger?.click());
    let menu = container.querySelector<HTMLElement>('[role="menu"]');
    let firstAction = menu?.querySelector<HTMLButtonElement>('[role="menuitem"]');
    expect(menu?.textContent).toContain("Film 1080p");
    expect(menu?.id).toBe("research-result-term-menu");
    expect(trigger?.getAttribute("aria-expanded")).toBe("true");
    expect(document.activeElement).toBe(firstAction);

    act(() => {
      firstAction?.dispatchEvent(
        new KeyboardEvent("keydown", { bubbles: true, key: "Escape" }),
      );
    });
    expect(container.querySelector('[role="menu"]')).toBeNull();
    expect(document.activeElement).toBe(trigger);
    expect(trigger?.getAttribute("aria-expanded")).toBe("false");

    act(() => trigger?.click());
    menu = container.querySelector<HTMLElement>('[role="menu"]');
    firstAction = menu?.querySelector<HTMLButtonElement>('[role="menuitem"]');
    await act(async () => {
      firstAction?.click();
      await Promise.resolve();
    });
    expect(onAddTerm).toHaveBeenCalledWith("Film 1080p", "query_terms");
    expect(document.activeElement).toBe(trigger);
  });

  it("does not suppress the native title context menu for viewers", () => {
    renderTable(false, vi.fn(async () => "Regola aggiornata"));

    expect(container.querySelector('[aria-haspopup="menu"]')).toBeNull();
    const title = Array.from(container.querySelectorAll("strong")).find(
      (element) => element.textContent === "Film 1080p",
    );
    expect(title?.classList.contains("research-result-title")).toBe(false);

    const contextMenu = new MouseEvent("contextmenu", {
      bubbles: true,
      cancelable: true,
    });
    act(() => title?.dispatchEvent(contextMenu));
    expect(contextMenu.defaultPrevented).toBe(false);
    expect(container.querySelector('[role="menu"]')).toBeNull();
    expect(container.querySelector('input[type="checkbox"]')).toBeNull();
    expect(container.querySelector(".research-select-all")).toBeNull();
    expect(container.querySelector(".research-result-batch-actions")).toBeNull();
  });

  it("restores the trigger focus when adding a term fails", async () => {
    renderTable(true, vi.fn(async () => { throw new Error("Save failed"); }));
    const trigger = container.querySelector<HTMLButtonElement>(
      '[aria-label="Apri menu termini per Film 1080p"]',
    );
    act(() => trigger?.click());
    const firstAction = container.querySelector<HTMLButtonElement>('[role="menuitem"]');

    await act(async () => {
      firstAction?.click();
      await Promise.resolve();
    });

    expect(container.querySelector('[role="menu"]')).toBeNull();
    expect(document.activeElement).toBe(trigger);
    expect(container.textContent).toContain("Save failed");
  });

  it("keeps valid selections while streaming appends and resets them for a new result set", () => {
    renderResults(
      [{ title: "Film A", resolution: "1080p" }],
      1,
    );
    const first = container.querySelector<HTMLInputElement>(
      '[aria-label="Seleziona Film A"]',
    );
    act(() => first?.click());
    expect(first?.checked).toBe(true);

    renderResults(
      [
        { title: "Film A", resolution: "1080p" },
        { title: "Film B", resolution: "2160p" },
      ],
      1,
    );
    expect(
      container.querySelector<HTMLInputElement>('[aria-label="Seleziona Film A"]')
        ?.checked,
    ).toBe(true);

    renderResults(
      [
        { title: "Film B", resolution: "2160p" },
        { title: "Film A", resolution: "1080p" },
      ],
      1,
    );
    expect(
      container.querySelector<HTMLInputElement>('[aria-label="Seleziona Film A"]')
        ?.checked,
    ).toBe(true);
    expect(
      container.querySelector<HTMLInputElement>('[aria-label="Seleziona Film B"]')
        ?.checked,
    ).toBe(false);

    renderResults(
      [{ title: "Film A", resolution: "1080p" }],
      2,
    );
    expect(
      container.querySelector<HTMLInputElement>('[aria-label="Seleziona Film A"]')
        ?.checked,
    ).toBe(false);
  });

  it("keeps a selected source when final results rotate refs and regroup it as a duplicate", () => {
    renderResults(
      [
        {
          title: "Film A",
          resolution: "1080p",
          indexer: "Prowlarr",
          size_gb: 1.5,
          torrent_ref: "ohsdl_stream_primary",
        },
        {
          title: "Film A",
          resolution: "1080p",
          indexer: "Jackett",
          size_gb: 1.5,
          torrent_ref: "ohsdl_stream_duplicate",
        },
      ],
      1,
    );
    const streamingRows = container.querySelectorAll<HTMLInputElement>(
      '[aria-label="Seleziona Film A"]',
    );
    act(() => streamingRows[1]?.click());
    expect(streamingRows[0]?.checked).toBe(false);
    expect(streamingRows[1]?.checked).toBe(true);

    renderResults(
      [
        {
          title: "Film A",
          resolution: "1080p",
          indexer: "Prowlarr",
          size_gb: 1.5,
          torrent_ref: "ohsdl_final_primary",
          duplicates: [
            {
              title: "Film A",
              resolution: "1080p",
              indexer: "Jackett",
              size_gb: 1.5,
              torrent_ref: "ohsdl_final_duplicate",
            },
          ],
        },
      ],
      1,
    );

    expect(
      container.querySelector<HTMLInputElement>('[aria-label="Seleziona Film A"]')
        ?.checked,
    ).toBe(false);
    expect(
      container.querySelector<HTMLInputElement>(
        '[aria-label="Seleziona fonte Film A"]',
      )?.checked,
    ).toBe(true);
  });

  function renderTable(
    canMutate: boolean,
    onAddTerm: (term: string, field: "query_terms" | "filter_terms" | "exclude_terms") => Promise<string>,
  ) {
    act(() => {
      root.render(
        <WorkspaceCapabilitiesProvider canMutate={canMutate}>
          <SearchResultTable
            results={[{ title: "Film 1080p", resolution: "1080p" }]}
            qbittorrentAvailable={false}
            onAddTerm={onAddTerm}
          />
        </WorkspaceCapabilitiesProvider>,
      );
    });
  }

  function renderResults(
    results: Array<{
      title: string;
      resolution: string;
      indexer?: string;
      size_gb?: number;
      torrent_ref?: string;
      duplicates?: Array<{
        title: string;
        resolution: string;
        indexer?: string;
        size_gb?: number;
        torrent_ref?: string;
      }>;
    }>,
    resultSetId: number,
  ) {
    act(() => {
      root.render(
        <WorkspaceCapabilitiesProvider canMutate>
          <SearchResultTable
            results={results}
            qbittorrentAvailable={false}
            resultSetId={resultSetId}
          />
        </WorkspaceCapabilitiesProvider>,
      );
    });
  }
});
