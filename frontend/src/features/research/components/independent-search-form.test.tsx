// @vitest-environment jsdom

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act } from "react";
import { flushSync } from "react-dom";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { getTmdbTvDetails, requestFromJellyseerr } from "@/features/research/api";
import { IndependentSearchForm } from "@/features/research/components/independent-search-form";
import {
  customRulesStorageKey,
  storeCustomRules,
} from "@/features/research/customization";
import { WorkspaceCapabilitiesProvider } from "@/features/session/workspace-capabilities";
import type {
  ResearchOverview,
  TmdbSearchResult,
} from "@/features/research/types";

vi.mock("@/features/research/api", () => ({
  getTmdbTvDetails: vi.fn(),
  requestFromJellyseerr: vi.fn(),
}));

vi.mock("@/features/research/components/tmdb-search-picker", () => ({
  TmdbSearchPicker: ({
    onSelect,
    selected,
  }: {
    onSelect: (result: TmdbSearchResult) => void;
    selected: TmdbSearchResult | null;
  }) => <>
    <span data-testid="selected-title">{selected?.title}</span>
    <button
      type="button"
      data-testid="select-tv"
      onClick={() =>
        onSelect({ tmdb_id: 101, title: "Serie test", media_type: "tv" })
      }
    >
      Seleziona serie
    </button>
    <button
      type="button"
      data-testid="select-movie-a"
      onClick={() =>
        onSelect({ tmdb_id: 201, title: "Film A", media_type: "movie" })
      }
    >
      Seleziona film A
    </button>
    <button
      type="button"
      data-testid="select-movie-b"
      onClick={() =>
        onSelect({ tmdb_id: 202, title: "Film B", media_type: "movie" })
      }
    >
      Seleziona film B
    </button>
  </>,
}));

declare global {
  var IS_REACT_ACT_ENVIRONMENT: boolean | undefined;
}

type Deferred<T> = {
  promise: Promise<T>;
  resolve: (value: T) => void;
};

function deferred<T>(): Deferred<T> {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((complete) => {
    resolve = complete;
  });
  return { promise, resolve };
}

const overview = {
  success: true,
  has_config: true,
  qbittorrent_available: false,
  scan: {},
  results: {},
  requests: [],
  movie_requests: [],
  tv_requests: [],
  search_rules: { use_prowlarr: true },
  search_defaults: { target_languages: [], exclude_tags: [] },
  movie_sort_options: [],
  tv_sort_options: [],
  auto_tasks: {},
  probe_counts: { blacklist: 0, incomplete: 0 },
} satisfies ResearchOverview;

const tvDetails = {
  success: true,
  details: {
    seasons: [
      { season_number: 1 },
      { season_number: 2 },
      { season_number: 3 },
    ],
  },
};

describe("IndependentSearchForm", () => {
  let container: HTMLDivElement;
  let root: ReturnType<typeof createRoot>;
  let queryClient: QueryClient;

  beforeEach(() => {
    globalThis.IS_REACT_ACT_ENVIRONMENT = true;
    window.localStorage.clear();
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
    globalThis.IS_REACT_ACT_ENVIRONMENT = undefined;
    vi.clearAllMocks();
  });

  it("preserves restored TV seasons when TMDB details arrive later", async () => {
    const details = deferred<typeof tvDetails>();
    vi.mocked(getTmdbTvDetails).mockReturnValue(details.promise);

    await act(async () => {
      root.render(
        <QueryClientProvider client={queryClient}>
          <IndependentSearchForm
            overview={overview}
            initialSearch={{
              query: "Serie test",
              mediaType: "tv",
              indexers: ["prowlarr"],
              tmdbId: 101,
              seasons: [2],
            }}
            searching={false}
            onSearch={vi.fn()}
            onSearchStart={vi.fn()}
          />
        </QueryClientProvider>,
      );
    });

    await resolveDetails(details);
    await waitForSelectedSeasons(container, ["S02"]);

    expect(selectedSeasons(container)).toEqual(["S02"]);
  });

  it("selects every regular season by default for a new TV title", async () => {
    const details = deferred<typeof tvDetails>();
    vi.mocked(getTmdbTvDetails).mockReturnValue(details.promise);

    await act(async () => {
      root.render(
        <QueryClientProvider client={queryClient}>
          <IndependentSearchForm
            overview={overview}
            searching={false}
            onSearch={vi.fn()}
            onSearchStart={vi.fn()}
          />
        </QueryClientProvider>,
      );
    });

    act(() => {
      container
        .querySelector<HTMLButtonElement>("[data-testid='select-tv']")
        ?.click();
    });
    await resolveDetails(details);
    await waitForSelectedSeasons(container, ["S01", "S02", "S03"]);

    expect(selectedSeasons(container)).toEqual(["S01", "S02", "S03"]);
  });

  it("requires seasons only for Jellyseerr and keeps generic TV search available", async () => {
    const details = deferred<typeof tvDetails>();
    vi.mocked(getTmdbTvDetails).mockReturnValue(details.promise);

    await renderForm(root, queryClient);
    act(() => {
      container
        .querySelector<HTMLButtonElement>("[data-testid='select-tv']")
        ?.click();
    });

    expect(buttonByText(container, "Cerca")?.disabled).toBe(false);
    expect(buttonByText(container, "Richiedi a Jellyseerr")?.disabled).toBe(true);

    await resolveDetails(details);
    await waitForSelectedSeasons(container, ["S01", "S02", "S03"]);
    expect(buttonByText(container, "Cerca")?.disabled).toBe(false);
    expect(buttonByText(container, "Richiedi a Jellyseerr")?.disabled).toBe(false);

    act(() => {
      container
        .querySelectorAll<HTMLInputElement>(".research-seasons input")
        .forEach((input) => input.click());
    });
    expect(buttonByText(container, "Cerca")?.disabled).toBe(false);
    expect(buttonByText(container, "Richiedi a Jellyseerr")?.disabled).toBe(true);
  });

  it("clears an incompatible TMDB selection when the media type changes", async () => {
    vi.mocked(getTmdbTvDetails).mockResolvedValue(tvDetails);
    const onSearch = vi.fn().mockResolvedValue(undefined);

    await act(async () => {
      root.render(
        <QueryClientProvider client={queryClient}>
          <IndependentSearchForm
            overview={overview}
            searching={false}
            onSearch={onSearch}
            onSearchStart={vi.fn()}
          />
        </QueryClientProvider>,
      );
    });

    act(() => {
      container
        .querySelector<HTMLButtonElement>("[data-testid='select-tv']")
        ?.click();
    });

    const mediaType = container.querySelector<HTMLSelectElement>(
      "#research-media-type",
    );
    expect(mediaType).not.toBeNull();
    act(() => {
      if (!mediaType) return;
      mediaType.value = "movie";
      mediaType.dispatchEvent(new Event("change", { bubbles: true }));
    });

    expect(container.querySelector(".research-seasons")).toBeNull();
    await act(async () => {
      container
        .querySelector<HTMLFormElement>("form")
        ?.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }));
      await Promise.resolve();
    });

    expect(onSearch).toHaveBeenCalledWith(expect.objectContaining({
      mediaType: "movie",
      seasons: [],
    }));
    expect(onSearch.mock.calls[0][0]).not.toHaveProperty("tmdbId");
  });

  it("does not attach a completed Jellyseerr request to a newer title", async () => {
    const firstRequest = deferred<{ success: boolean; message: string }>();
    vi.mocked(requestFromJellyseerr).mockReturnValueOnce(firstRequest.promise);
    await renderForm(root, queryClient);

    act(() => {
      container.querySelector<HTMLButtonElement>("[data-testid='select-movie-a']")?.click();
    });
    act(() => buttonByText(container, "Richiedi a Jellyseerr")?.click());
    expect(requestFromJellyseerr).toHaveBeenCalledWith(201, "movie", []);

    act(() => {
      container.querySelector<HTMLButtonElement>("[data-testid='select-movie-b']")?.click();
    });
    await act(async () => {
      firstRequest.resolve({ success: true, message: "Film A richiesto" });
      await firstRequest.promise;
    });

    expect(container.textContent).toContain("Film B");
    expect(container.textContent).not.toContain("Film A richiesto");
    expect(buttonByText(container, "Richiedi a Jellyseerr")?.disabled).toBe(false);
  });

  it("does not enable or persist custom rules just by reopening the form", async () => {
    await renderForm(root, queryClient);

    expect(customRulesToggle(container).checked).toBe(false);
    expect(window.localStorage.getItem(customRulesStorageKey(1) || "")).toBeNull();

    await act(async () => {
      root.render(<></>);
    });
    await renderForm(root, queryClient);

    expect(customRulesToggle(container).checked).toBe(false);
    expect(window.localStorage.getItem(customRulesStorageKey(1) || "")).toBeNull();
  });

  it("restores custom rules only after the user explicitly enables them", async () => {
    await renderForm(root, queryClient);

    act(() => customRulesToggle(container).click());

    expect(JSON.parse(window.localStorage.getItem(customRulesStorageKey(1) || "") || "null"))
      .toMatchObject({ enabled: true, rules: { search_rules: {} } });

    await act(async () => {
      root.render(<></>);
    });
    await renderForm(root, queryClient);

    expect(customRulesToggle(container).checked).toBe(true);
  });

  it("switches custom-rule ownership on account change and clears it on logout", async () => {
    const enabledRules = {
      search_rules: { min_seeders: 7 },
      target_languages: ["ita"],
      exclude_tags: ["account-one"],
    };
    storeCustomRules(1, true, enabledRules);
    storeCustomRules(2, false, { ...enabledRules, exclude_tags: ["account-two"] });

    await renderForm(root, queryClient, 1);
    expect(customRulesToggle(container).checked).toBe(true);

    await renderForm(root, queryClient, 2);
    expect(customRulesToggle(container).checked).toBe(false);

    await renderForm(root, queryClient, null);
    expect(customRulesToggle(container).checked).toBe(false);
  });

  it("is noninteractive immediately on a same-role owner transition before passive effects", async () => {
    const accountOneRules = {
      search_rules: { query_terms: ["account-one-private"] },
      target_languages: ["ita"],
      exclude_tags: ["account-one"],
    };
    storeCustomRules(1, true, accountOneRules);
    await renderForm(root, queryClient, 1);
    expect(customRulesToggle(container).checked).toBe(true);

    globalThis.IS_REACT_ACT_ENVIRONMENT = false;
    flushSync(() => root.render(formTree(queryClient, 2)));
    const transitionToggle = customRulesToggle(container);
    expect(transitionToggle.checked).toBe(false);
    expect(transitionToggle.disabled).toBe(true);
    transitionToggle.click();
    expect(window.localStorage.getItem(customRulesStorageKey(2) || "")).toBeNull();

    globalThis.IS_REACT_ACT_ENVIRONMENT = true;
    await act(async () => undefined);
  });
});

async function renderForm(
  root: ReturnType<typeof createRoot>,
  queryClient: QueryClient,
  accountId: number | null = 1,
) {
  await act(async () => {
    root.render(formTree(queryClient, accountId));
  });
}

function formTree(queryClient: QueryClient, accountId: number | null) {
  return (
    <QueryClientProvider client={queryClient}>
      <WorkspaceCapabilitiesProvider accountId={accountId} canMutate>
        <IndependentSearchForm
          overview={overview}
          searching={false}
          onSearch={vi.fn()}
          onSearchStart={vi.fn()}
        />
      </WorkspaceCapabilitiesProvider>
    </QueryClientProvider>
  );
}

function customRulesToggle(container: HTMLElement) {
  const toggle = [...container.querySelectorAll<HTMLInputElement>("input[type='checkbox']")]
    .find((input) => input.parentElement?.textContent?.includes("Personalizza regole"));
  if (!toggle) throw new Error("Custom-rules toggle not found");
  return toggle;
}

async function resolveDetails(details: Deferred<typeof tvDetails>) {
  await act(async () => {
    details.resolve(tvDetails);
    await details.promise;
  });
}

async function waitForSelectedSeasons(
  container: HTMLElement,
  expected: string[],
) {
  for (let attempt = 0; attempt < 20; attempt += 1) {
    if (JSON.stringify(selectedSeasons(container)) === JSON.stringify(expected)) return;
    await act(async () => {
      await new Promise((resolve) => window.setTimeout(resolve, 0));
    });
  }
}

function selectedSeasons(container: HTMLElement) {
  return [...container.querySelectorAll<HTMLLabelElement>(".research-seasons label")]
    .filter((label) => label.querySelector("input")?.checked)
    .map((label) => label.textContent?.trim());
}

function buttonByText(container: HTMLElement, text: string) {
  return Array.from(container.querySelectorAll<HTMLButtonElement>("button")).find(
    (button) => button.textContent?.includes(text),
  );
}
