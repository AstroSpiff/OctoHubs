// @vitest-environment jsdom

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { searchTmdb } from "@/features/research/api";
import { TmdbSearchPicker } from "@/features/research/components/tmdb-search-picker";

vi.mock("@/features/research/api", () => ({
  checkEmbyAvailability: vi.fn(),
  searchTmdb: vi.fn(),
}));

vi.mock("@/features/research/components/emby-media-browser", () => ({
  EmbyMediaBrowser: ({ selected }: { selected: { tmdb_id: number } }) => (
    <div data-testid="emby-browser">Target {selected.tmdb_id}</div>
  ),
}));

declare global {
  var IS_REACT_ACT_ENVIRONMENT: boolean | undefined;
}

const suggestion = {
  tmdb_id: 348,
  title: "Alien",
  media_type: "movie" as const,
  year: 1979,
};

describe("TmdbSearchPicker suggestion disclosure", () => {
  let container: HTMLDivElement;
  let root: ReturnType<typeof createRoot>;
  let queryClient: QueryClient;
  let onSelect: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    globalThis.IS_REACT_ACT_ENVIRONMENT = true;
    vi.useFakeTimers();
    vi.mocked(searchTmdb).mockResolvedValue({
      success: true,
      results: [suggestion],
      page: 1,
      total_pages: 1,
    });
    onSelect = vi.fn();
    queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
    container = document.createElement("div");
    document.body.append(container);
    root = createRoot(container);
  });

  afterEach(() => {
    act(() => root.unmount());
    queryClient.clear();
    container.remove();
    vi.useRealTimers();
    vi.clearAllMocks();
    globalThis.IS_REACT_ACT_ENVIRONMENT = undefined;
  });

  it("closes suggestions when focus leaves the picker", async () => {
    await renderSuggestions();
    const input = container.querySelector<HTMLInputElement>('[role="combobox"]');
    const option = container.querySelector<HTMLButtonElement>('[role="option"]');
    const outside = container.querySelector<HTMLButtonElement>("#outside-control");

    act(() => {
      input?.focus();
      option?.focus();
      outside?.focus();
    });

    expect(container.querySelector('[role="listbox"]')).toBeNull();
    expect(input?.hasAttribute("aria-controls")).toBe(false);
  });

  it("does not reopen after focus leaves while the request is pending", async () => {
    await renderPicker();
    const input = container.querySelector<HTMLInputElement>('[role="combobox"]');
    const outside = container.querySelector<HTMLButtonElement>("#outside-control");
    act(() => {
      input?.focus();
      outside?.focus();
    });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(300);
    });

    expect(searchTmdb).toHaveBeenCalledWith("Alien");
    expect(container.querySelector('[role="listbox"]')).toBeNull();
  });

  it("closes suggestions on an outside pointer", async () => {
    await renderSuggestions();
    const outside = container.querySelector<HTMLButtonElement>("#outside-control");
    act(() => {
      outside?.dispatchEvent(new Event("pointerdown", { bubbles: true }));
    });
    expect(container.querySelector('[role="listbox"]')).toBeNull();
  });

  it("closes suggestions with Escape after focus moves into the listbox", async () => {
    await renderSuggestions();
    const option = container.querySelector<HTMLButtonElement>('[role="option"]');
    act(() => {
      option?.focus();
      option?.dispatchEvent(
        new KeyboardEvent("keydown", { bubbles: true, key: "Escape" }),
      );
    });
    expect(container.querySelector('[role="listbox"]')).toBeNull();
  });

  it("keeps an inside pointer selection functional", async () => {
    await renderSuggestions();
    const option = container.querySelector<HTMLButtonElement>('[role="option"]');
    act(() => {
      option?.dispatchEvent(new Event("pointerdown", { bubbles: true }));
      option?.click();
    });

    expect(onSelect).toHaveBeenCalledWith(suggestion);
    expect(container.querySelector('[role="listbox"]')).toBeNull();
  });

  it("clears a failed search alert when the query becomes too short", async () => {
    vi.mocked(searchTmdb).mockRejectedValueOnce(new Error("TMDB unavailable"));
    await renderPicker();
    await act(async () => {
      await vi.advanceTimersByTimeAsync(300);
    });
    expect(container.querySelector('[role="alert"]')?.textContent).toContain("TMDB unavailable");

    await renderPicker("Al");

    expect(container.querySelector('[role="alert"]')).toBeNull();
  });

  it("resets the selected Emby server synchronously across A to B to A", async () => {
    const targetA = suggestion;
    const targetB = {
      tmdb_id: 349,
      title: "Aliens",
      media_type: "movie" as const,
      year: 1986,
    };
    for (const target of [targetA, targetB]) {
      queryClient.setQueryData(
        ["emby-availability", target.tmdb_id, target.media_type],
        {
          success: true,
          available_on: [
            {
              server_id: "server-shared",
              server_name: "Emby principale",
              item_id: `item-${target.tmdb_id}`,
            },
            {
              server_id: "server-peer",
              server_name: "Emby secondario",
              item_id: `peer-${target.tmdb_id}`,
            },
          ],
        },
      );
    }

    await renderSelected(targetA);
    const primary = buttonWithText(container, "Emby principale");
    const secondary = buttonWithText(container, "Emby secondario");
    expect(primary.getAttribute("aria-pressed")).toBe("false");
    expect(secondary.getAttribute("aria-pressed")).toBe("false");

    act(() => primary.click());
    expect(primary.getAttribute("aria-pressed")).toBe("true");
    expect(secondary.getAttribute("aria-pressed")).toBe("false");
    expect(container.querySelector('[data-testid="emby-browser"]')?.textContent)
      .toBe("Target 348");

    await renderSelected(targetB);
    expect(container.querySelector('[data-testid="emby-browser"]')).toBeNull();
    expect(buttonWithText(container, "Emby principale").getAttribute("aria-pressed"))
      .toBe("false");

    await renderSelected(targetA);
    expect(container.querySelector('[data-testid="emby-browser"]')).toBeNull();
    expect(buttonWithText(container, "Emby principale").getAttribute("aria-pressed"))
      .toBe("false");
  });

  async function renderSuggestions() {
    await renderPicker();
    await act(async () => {
      await vi.advanceTimersByTimeAsync(300);
    });
    expect(container.querySelector('[role="listbox"]')).not.toBeNull();
  }

  async function renderPicker(query = "Alien") {
    await act(async () => {
      root.render(
        <QueryClientProvider client={queryClient}>
          <TmdbSearchPicker
            query={query}
            selected={null}
            onClear={vi.fn()}
            onQueryChange={vi.fn()}
            onSelect={onSelect}
          />
          <button id="outside-control" type="button">Altro controllo</button>
        </QueryClientProvider>,
      );
    });
  }

  async function renderSelected(selected: typeof suggestion) {
    await act(async () => {
      root.render(
        <QueryClientProvider client={queryClient}>
          <TmdbSearchPicker
            query={selected.title}
            selected={selected}
            onClear={vi.fn()}
            onQueryChange={vi.fn()}
            onSelect={onSelect}
          />
        </QueryClientProvider>,
      );
    });
  }
});

function buttonWithText(container: HTMLElement, text: string) {
  const button = [...container.querySelectorAll<HTMLButtonElement>("button")]
    .find((candidate) => candidate.textContent?.includes(text));
  if (!button) throw new Error(`Button not found: ${text}`);
  return button;
}
