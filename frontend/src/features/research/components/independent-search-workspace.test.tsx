// @vitest-environment jsdom

import { renderToStaticMarkup } from "react-dom/server";
import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, describe, expect, it, vi } from "vitest";

import { IndependentSearchWorkspace } from "@/features/research/components/independent-search-workspace";
import type { ResearchOverview } from "@/features/research/types";
import { WorkspaceCapabilitiesProvider } from "@/features/session/workspace-capabilities";
import { StreamingSearchPartialError } from "@/features/research/use-streaming-search";

const mocks = vi.hoisted(() => ({
  onRepeat: null as null | ((input: Record<string, unknown>) => Promise<void>),
  start: vi.fn(),
  warning: "",
}));

vi.mock("@/features/research/components/independent-search-form", () => ({
  IndependentSearchForm: () => <div>CANARY_SEARCH_FORM</div>,
}));
vi.mock("@/features/research/components/manual-search-history", () => ({
  ManualSearchHistory: (props: {
    onRepeat: (input: Record<string, unknown>) => Promise<void>;
    refreshToken: number;
  }) => {
    mocks.onRepeat = props.onRepeat;
    return <div data-refresh-token={props.refreshToken}>CANARY_HISTORY</div>;
  },
}));
vi.mock("@/features/research/components/search-results", () => ({
  SearchResults: () => <div>CANARY_RESULTS</div>,
}));
vi.mock("@/features/research/use-streaming-search", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/features/research/use-streaming-search")>()),
  useStreamingSearch: () => ({
    error: null,
    progress: null,
    results: [],
    running: false,
    start: mocks.start,
    warning: mocks.warning,
  }),
}));

const overview = {
  qbittorrent_available: false,
} as ResearchOverview;

describe("IndependentSearchWorkspace capabilities", () => {
  afterEach(() => {
    mocks.onRepeat = null;
    mocks.start.mockReset();
    mocks.warning = "";
    document.body.replaceChildren();
    globalThis.IS_REACT_ACT_ENVIRONMENT = undefined;
  });

  it.each([
    [false, false],
    [true, true],
  ])("shows the mutable form with canMutate=%s only when writable", (canMutate, visible) => {
    const markup = renderToStaticMarkup(
      <WorkspaceCapabilitiesProvider canMutate={canMutate}>
        <IndependentSearchWorkspace overview={overview} />
      </WorkspaceCapabilitiesProvider>,
    );

    expect(markup.includes("CANARY_SEARCH_FORM")).toBe(visible);
    expect(markup).toContain("CANARY_HISTORY");
    expect(markup).toContain("CANARY_RESULTS");
  });

  it("refreshes history and exposes the warning when Repeat ends partially", async () => {
    globalThis.IS_REACT_ACT_ENVIRONMENT = true;
    mocks.warning = "Ricerca completata parzialmente";
    mocks.start.mockRejectedValue(
      new StreamingSearchPartialError("Ricerca completata parzialmente", true),
    );
    const container = document.createElement("div");
    document.body.append(container);
    const root = createRoot(container);
    await act(async () => {
      root.render(
        <WorkspaceCapabilitiesProvider canMutate>
          <IndependentSearchWorkspace overview={overview} />
        </WorkspaceCapabilitiesProvider>,
      );
    });

    await act(async () => {
      await mocks.onRepeat?.({
        query: "Alien",
        mediaType: "movie",
        indexers: ["prowlarr"],
        seasons: [],
      }).catch(() => undefined);
    });

    expect(container.textContent).toContain("Ricerca completata parzialmente");
    expect(container.querySelector("[data-refresh-token='1']")).not.toBeNull();
    act(() => root.unmount());
  });
});
