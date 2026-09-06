// @vitest-environment jsdom

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act } from "react";
import { createRoot } from "react-dom/client";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  getJellyseerrRefreshStatus,
  refreshJellyseerrRequests,
  saveRequestSearchRules,
} from "@/features/research/api";
import { JellyseerrRequestsWorkspace } from "@/features/research/components/jellyseerr-requests-workspace";
import type { ResearchOverview } from "@/features/research/types";

vi.mock("@/features/research/api", () => ({
  getJellyseerrRefreshStatus: vi.fn(),
  refreshJellyseerrRequests: vi.fn(),
  saveRequestSearchRules: vi.fn(),
}));

declare global {
  var IS_REACT_ACT_ENVIRONMENT: boolean | undefined;
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
  all_requests: [],
  all_movie_requests: [],
  all_tv_requests: [],
  search_rules: {} as ResearchOverview["search_rules"],
  search_defaults: { target_languages: [], exclude_tags: [] },
  movie_sort_options: [],
  tv_sort_options: [],
  auto_tasks: {},
  probe_counts: { blacklist: 0, incomplete: 0 },
} satisfies ResearchOverview;

describe("JellyseerrRequestsWorkspace refresh status", () => {
  let container: HTMLDivElement;
  let root: ReturnType<typeof createRoot>;

  beforeEach(() => {
    globalThis.IS_REACT_ACT_ENVIRONMENT = true;
    container = document.createElement("div");
    document.body.appendChild(container);
    root = createRoot(container);
    window.matchMedia = vi.fn().mockReturnValue({
      matches: false,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
    });
  });

  afterEach(() => {
    act(() => root.unmount());
    container.remove();
    vi.resetAllMocks();
    globalThis.IS_REACT_ACT_ENVIRONMENT = undefined;
  });

  it("reports a status request failure instead of a false refresh success", async () => {
    vi.mocked(refreshJellyseerrRequests).mockResolvedValue({
      success: true,
      message: "Aggiornamento richieste avviato.",
    });
    vi.mocked(getJellyseerrRefreshStatus).mockRejectedValue(
      new Error("Stato Jellyseerr non disponibile"),
    );
    const onRefresh = vi.fn();
    const client = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });

    await act(async () => {
      root.render(
        <QueryClientProvider client={client}>
          <MemoryRouter>
            <JellyseerrRequestsWorkspace
              overview={overview}
              onRefresh={onRefresh}
            />
          </MemoryRouter>
        </QueryClientProvider>,
      );
    });

    await act(async () => {
      [...container.querySelectorAll<HTMLButtonElement>("button")]
        .find((button) => button.textContent?.includes("Aggiorna lista"))
        ?.click();
      await Promise.resolve();
      await Promise.resolve();
    });

    for (let attempt = 0; attempt < 20; attempt += 1) {
      if (container.textContent?.includes("Stato Jellyseerr non disponibile")) break;
      await act(async () => {
        await new Promise((resolve) => window.setTimeout(resolve, 5));
      });
    }
    expect(container.textContent).toContain("Stato Jellyseerr non disponibile");
    expect(container.textContent).not.toContain("Lista richieste aggiornata.");
    expect(onRefresh).not.toHaveBeenCalled();
  });

  it("keeps an accepted autosave draft while the overview prop is still stale", async () => {
    const movieRequest = {
      id: 9,
      media_type: "movie",
      title: "Film test",
      rules: { enabled: true },
    };
    const requestOverview = {
      ...overview,
      requests: [movieRequest],
      movie_requests: [movieRequest],
      all_requests: [movieRequest],
      all_movie_requests: [movieRequest],
    } as ResearchOverview;
    vi.mocked(saveRequestSearchRules).mockResolvedValue({
      success: true,
      message: "Regole aggiornate",
    });
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });

    await act(async () => {
      root.render(
        <QueryClientProvider client={client}>
          <MemoryRouter>
            <JellyseerrRequestsWorkspace overview={requestOverview} onRefresh={() => undefined} />
          </MemoryRouter>
        </QueryClientProvider>,
      );
    });
    const enabled = container.querySelector<HTMLInputElement>('input[aria-label="Abilita Film test"]');
    expect(enabled?.checked).toBe(true);

    await act(async () => {
      enabled?.click();
      await new Promise((resolve) => window.setTimeout(resolve, 700));
    });
    for (let attempt = 0; attempt < 20 && vi.mocked(saveRequestSearchRules).mock.calls.length === 0; attempt += 1) {
      await act(async () => new Promise((resolve) => window.setTimeout(resolve, 10)));
    }

    expect(saveRequestSearchRules).toHaveBeenCalledOnce();
    expect(
      container.querySelector<HTMLInputElement>('input[aria-label="Abilita Film test"]')?.checked,
    ).toBe(false);
    expect(container.textContent).toContain("Regole aggiornate");
  });
});
