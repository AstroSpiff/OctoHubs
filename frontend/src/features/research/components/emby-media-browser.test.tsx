// @vitest-environment jsdom

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  getEmbyItemDetails,
  getEmbyMovieVersions,
  getEmbySeasonEpisodes,
  getEmbySeriesSeasons,
} from "@/features/research/api";
import { EmbyMediaBrowser } from "@/features/research/components/emby-media-browser";

vi.mock("@/features/research/api", () => ({
  getEmbyItemDetails: vi.fn(),
  getEmbyMovieVersions: vi.fn(),
  getEmbySeasonEpisodes: vi.fn(),
  getEmbySeriesSeasons: vi.fn(),
}));

declare global {
  var IS_REACT_ACT_ENVIRONMENT: boolean | undefined;
}

describe("EmbyMediaBrowser TV navigation", () => {
  let container: HTMLDivElement;
  let queryClient: QueryClient;
  let root: ReturnType<typeof createRoot>;

  beforeEach(() => {
    globalThis.IS_REACT_ACT_ENVIRONMENT = true;
    queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
    container = document.createElement("div");
    document.body.append(container);
    root = createRoot(container);

    vi.mocked(getEmbySeriesSeasons).mockResolvedValue({
      success: true,
      seasons: [
        { season_id: "season-1", season_number: 1 },
        { season_id: "season-2", season_number: 2 },
      ],
    });
    vi.mocked(getEmbySeasonEpisodes).mockImplementation(async (_serverId, seasonId) => ({
      success: true,
      episodes: seasonId === "season-1"
        ? [{
            episode_id: "episode-1",
            episode_number: 1,
            name: "Primo episodio",
            resolutions: [{ label: "1080p", item_id: "item-episode-1" }],
          }]
        : [],
    }));
    vi.mocked(getEmbyItemDetails).mockImplementation(async (_serverId, itemId) => ({
      success: true,
      details: itemId === "item-episode-1"
        ? { title: "Dettaglio S1E1", path: "/media/season-1/episode-1.mkv" }
        : itemId === "series-b"
          ? { title: "Serie B", path: "/media/b" }
        : { title: "Serie test" },
    }));
  });

  afterEach(() => {
    act(() => root.unmount());
    queryClient.clear();
    container.remove();
    vi.clearAllMocks();
    globalThis.IS_REACT_ACT_ENVIRONMENT = undefined;
  });

  it("clears the previous episode details when the season changes", async () => {
    await act(async () => {
      root.render(
        <QueryClientProvider client={queryClient}>
          <EmbyMediaBrowser
            selected={{ tmdb_id: 101, title: "Serie test", media_type: "tv" }}
            server={{ server_id: "server-1", server_name: "Emby", item_id: "series-1" }}
            onClose={vi.fn()}
          />
        </QueryClientProvider>,
      );
    });

    await waitForText(container, "S01");
    expect(buttonWithText(container, "S01").getAttribute("aria-pressed")).toBe("false");
    act(() => buttonWithText(container, "S01").click());
    await waitForText(container, "Primo episodio");
    expect(buttonWithText(container, "S01").getAttribute("aria-pressed")).toBe("true");
    expect(buttonWithText(container, "Primo episodio").getAttribute("aria-pressed")).toBe("false");

    act(() => buttonWithText(container, "Primo episodio").click());
    await waitForText(container, "Dettaglio S1E1");
    expect(buttonWithText(container, "Primo episodio").getAttribute("aria-pressed")).toBe("true");
    expect(container.textContent).toContain("/media/season-1/episode-1.mkv");

    act(() => buttonWithText(container, "S02").click());

    expect(container.textContent).not.toContain("Dettaglio S1E1");
    expect(container.textContent).not.toContain("/media/season-1/episode-1.mkv");
  });

  it("announces browser query failures to assistive technology", async () => {
    vi.mocked(getEmbySeriesSeasons).mockRejectedValueOnce(new Error("Emby non raggiungibile"));

    await act(async () => {
      root.render(
        <QueryClientProvider client={queryClient}>
          <EmbyMediaBrowser
            selected={{ tmdb_id: 101, title: "Serie test", media_type: "tv" }}
            server={{ server_id: "server-1", server_name: "Emby", item_id: "series-1" }}
            onClose={vi.fn()}
          />
        </QueryClientProvider>,
      );
    });

    await waitForText(container, "Emby non raggiungibile");
    expect(container.querySelector('[role="alert"]')?.textContent).toBe("Emby non raggiungibile");
  });

  it("never paints cached movie details from the previous target", async () => {
    vi.mocked(getEmbyMovieVersions).mockResolvedValue({ success: true, versions: [] });
    vi.mocked(getEmbyItemDetails).mockImplementation(async (_serverId, itemId) => ({
      success: true,
      details: itemId === "movie-a"
        ? { title: "Film A", path: "/media/a.mkv" }
        : { title: "Film B", path: "/media/b.mkv" },
    }));
    queryClient.setQueryData(
      ["emby-item-details", "server-1", "movie-a"],
      { success: true, details: { title: "Film A", path: "/media/a.mkv" } },
    );
    queryClient.setQueryData(
      ["emby-item-details", "server-1", "movie-b"],
      { success: true, details: { title: "Film B", path: "/media/b.mkv" } },
    );

    renderBrowserSynchronously(
      { tmdb_id: 101, title: "Film A", media_type: "movie" },
      { server_id: "server-1", server_name: "Emby", item_id: "movie-a" },
    );
    expect(container.textContent).toContain("/media/a.mkv");

    renderBrowserSynchronously(
      { tmdb_id: 202, title: "Film B", media_type: "movie" },
      { server_id: "server-1", server_name: "Emby", item_id: "movie-b" },
    );
    expect(container.textContent).not.toContain("/media/a.mkv");
    expect(container.textContent).toContain("/media/b.mkv");

    renderBrowserSynchronously(
      { tmdb_id: 101, title: "Film A", media_type: "movie" },
      { server_id: "server-1", server_name: "Emby", item_id: "movie-a" },
    );
    expect(container.textContent).not.toContain("/media/b.mkv");
    expect(container.textContent).toContain("/media/a.mkv");
  });

  it("clears cached season and episode state before a TV target paint", async () => {
    queryClient.setQueryData(
      ["emby-series-seasons", "server-1", "series-a"],
      { success: true, seasons: [{ season_id: "season-1", season_number: 1 }] },
    );
    queryClient.setQueryData(
      ["emby-season-episodes", "server-1", "season-1"],
      {
        success: true,
        episodes: [{
          episode_id: "episode-a",
          episode_number: 1,
          name: "Episodio A",
          resolutions: [{ label: "1080p", item_id: "episode-item-a" }],
        }],
      },
    );
    queryClient.setQueryData(
      ["emby-item-details", "server-1", "episode-item-a"],
      { success: true, details: { title: "Episodio A", path: "/media/a/e01.mkv" } },
    );
    queryClient.setQueryData(
      ["emby-item-details", "server-1", "series-b"],
      { success: true, details: { title: "Serie B", path: "/media/b" } },
    );

    await renderBrowser(
      { tmdb_id: 101, title: "Serie A", media_type: "tv" },
      { server_id: "server-1", server_name: "Emby", item_id: "series-a" },
    );
    act(() => buttonWithText(container, "S01").click());
    await waitForText(container, "Episodio A");
    act(() => buttonWithText(container, "Episodio A").click());
    await waitForText(container, "/media/a/e01.mkv");

    await renderBrowser(
      { tmdb_id: 202, title: "Serie B", media_type: "tv" },
      { server_id: "server-1", server_name: "Emby", item_id: "series-b" },
    );
    expect(container.textContent).not.toContain("Episodio A");
    expect(container.textContent).not.toContain("/media/a/e01.mkv");
    expect(container.textContent).toContain("/media/b");
  });

  async function renderBrowser(
    selected: { tmdb_id: number; title: string; media_type: "movie" | "tv" },
    server: { server_id: string; server_name: string; item_id: string },
  ) {
    await act(async () => {
      root.render(
        <QueryClientProvider client={queryClient}>
          <EmbyMediaBrowser selected={selected} server={server} onClose={vi.fn()} />
        </QueryClientProvider>,
      );
    });
  }

  function renderBrowserSynchronously(
    selected: { tmdb_id: number; title: string; media_type: "movie" | "tv" },
    server: { server_id: string; server_name: string; item_id: string },
  ) {
    act(() => {
      root.render(
        <QueryClientProvider client={queryClient}>
          <EmbyMediaBrowser selected={selected} server={server} onClose={vi.fn()} />
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

async function waitForText(container: HTMLElement, text: string) {
  for (let attempt = 0; attempt < 20; attempt += 1) {
    if (container.textContent?.includes(text)) return;
    await act(async () => {
      await new Promise((resolve) => window.setTimeout(resolve, 0));
    });
  }
  throw new Error(`Text not found: ${text}`);
}
