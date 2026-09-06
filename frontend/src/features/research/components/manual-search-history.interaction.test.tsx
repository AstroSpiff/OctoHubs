// @vitest-environment jsdom

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  deleteManualSearch,
  getManualSearchHistory,
} from "@/features/research/api";
import { ManualSearchHistory } from "@/features/research/components/manual-search-history";
import { WorkspaceCapabilitiesProvider } from "@/features/session/workspace-capabilities";

vi.mock("@/features/research/api", () => ({
  deleteManualSearch: vi.fn(),
  getManualSearchHistory: vi.fn(),
}));

declare global {
  var IS_REACT_ACT_ENVIRONMENT: boolean | undefined;
}

describe("ManualSearchHistory", () => {
  let container: HTMLDivElement;
  let root: ReturnType<typeof createRoot>;
  let client: QueryClient;

  beforeEach(() => {
    globalThis.IS_REACT_ACT_ENVIRONMENT = true;
    container = document.createElement("div");
    document.body.appendChild(container);
    root = createRoot(container);
    client = new QueryClient({
      defaultOptions: {
        queries: { retry: false },
        mutations: { retry: false },
      },
    });
  });

  afterEach(() => {
    act(() => root.unmount());
    client.clear();
    container.remove();
    vi.resetAllMocks();
    globalThis.IS_REACT_ACT_ENVIRONMENT = undefined;
  });

  it("announces a failed deletion with the affected history id", async () => {
    vi.mocked(getManualSearchHistory).mockResolvedValue({
      success: true,
      searches: [{
        id: 42,
        generated_at: "2026-09-03T12:00:00Z",
        search_context: { query: "Example", media_type: "movie" },
        items: [{ title: "Example", results_found: 1, results: [] }],
      }],
    });
    vi.mocked(deleteManualSearch).mockRejectedValue(new Error("Backend non disponibile"));

    await act(async () => {
      root.render(
        <QueryClientProvider client={client}>
          <ManualSearchHistory
            refreshToken={0}
            searching={false}
            onView={() => undefined}
            onEdit={() => undefined}
            onRepeat={() => Promise.resolve()}
          />
        </QueryClientProvider>,
      );
    });
    await waitForText(container, "Example");

    await act(async () => {
      container.querySelector<HTMLButtonElement>('[aria-label="Elimina dallo storico"]')?.click();
      await Promise.resolve();
    });
    const confirm = [...container.querySelectorAll<HTMLButtonElement>("button")]
      .find((button) => button.textContent?.includes("Elimina ricerca"));
    expect(confirm).toBeTruthy();

    await act(async () => {
      confirm?.click();
      await Promise.resolve();
      await Promise.resolve();
    });
    await waitForText(container, "Backend non disponibile");

    const alert = container.querySelector('[role="alert"]');
    expect(alert?.textContent).toContain("#42");
    expect(alert?.textContent).toContain("Backend non disponibile");
  });

  it("keeps read actions but hides every preparatory mutation from viewers", async () => {
    vi.mocked(getManualSearchHistory).mockResolvedValue({
      success: true,
      searches: [{
        id: 42,
        generated_at: "2026-09-03T12:00:00Z",
        search_context: { query: "Example", media_type: "movie" },
        items: [{ title: "Example", results_found: 1, results: [] }],
      }],
    });

    await act(async () => {
      root.render(
        <QueryClientProvider client={client}>
          <WorkspaceCapabilitiesProvider canMutate={false}>
            <ManualSearchHistory
              refreshToken={0}
              searching={false}
              onView={() => undefined}
              onEdit={() => undefined}
              onRepeat={() => Promise.resolve()}
            />
          </WorkspaceCapabilitiesProvider>
        </QueryClientProvider>,
      );
    });
    await waitForText(container, "Example");

    expect(container.querySelector('[title="Visualizza risultati"]')).not.toBeNull();
    expect(container.querySelector('[aria-label="Modifica ricerca"]')).toBeNull();
    expect(container.querySelector('[aria-label="Ripeti ricerca"]')).toBeNull();
    expect(container.querySelector('[aria-label="Elimina dallo storico"]')).toBeNull();
  });
});

async function waitForText(container: HTMLElement, text: string) {
  for (let attempt = 0; attempt < 30; attempt += 1) {
    if (container.textContent?.includes(text)) return;
    await act(async () => {
      await new Promise((resolve) => window.setTimeout(resolve, 5));
    });
  }
  throw new Error(`Testo non trovato: ${text}`);
}
