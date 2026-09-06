// @vitest-environment jsdom

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  getCollectionSourceInventory,
  getTraktLists,
  saveCollectionSourceInventory,
} from "@/features/collections/api";
import { CollectionSourcesPanel } from "@/features/collections/components/collection-sources-panel";

vi.mock("@/features/collections/api", () => ({
  deleteCollectionSourceInventory: vi.fn(),
  getCollectionSourceInventory: vi.fn(),
  getMdbListLists: vi.fn(),
  getTraktLists: vi.fn(),
  saveCollectionSourceInventory: vi.fn(),
}));

declare global {
  var IS_REACT_ACT_ENVIRONMENT: boolean | undefined;
}

const options = {
  success: true,
  source_types: [{ value: "trakt_list", label: "Lista Trakt" }],
  servers: [],
  trakt_enabled: true,
  mdblist_enabled: false,
};

describe("CollectionSourcesPanel refresh lifecycle", () => {
  let container: HTMLDivElement;
  let root: ReturnType<typeof createRoot>;
  let client: QueryClient;

  beforeEach(() => {
    globalThis.IS_REACT_ACT_ENVIRONMENT = true;
    vi.mocked(getCollectionSourceInventory).mockResolvedValue({
      success: true,
      items: [],
    });
    client = new QueryClient({
      defaultOptions: { queries: { retry: 2, refetchOnWindowFocus: true } },
    });
    container = document.createElement("div");
    document.body.appendChild(container);
    root = createRoot(container);
  });

  afterEach(() => {
    act(() => root.unmount());
    container.remove();
    client.clear();
    vi.resetAllMocks();
    globalThis.IS_REACT_ACT_ENVIRONMENT = undefined;
  });

  async function renderPanel() {
    await act(async () => {
      root.render(
        <QueryClientProvider client={client}>
          <CollectionSourcesPanel
            enabled
            options={options}
            onSelect={vi.fn()}
          />
        </QueryClientProvider>,
      );
      await Promise.resolve();
    });
  }

  it("does not repeat a side-effectful refresh after a query failure", async () => {
    vi.mocked(getTraktLists).mockRejectedValue(
      new Error("Trakt non disponibile"),
    );

    await renderPanel();
    await act(async () => {
      await vi.waitFor(() => {
        expect(container.textContent).toContain("Trakt non disponibile");
      });
    });

    expect(getTraktLists).toHaveBeenCalledOnce();
  });

  it("aborts the source refresh when the panel is unmounted", async () => {
    let signal: AbortSignal | undefined;
    vi.mocked(getTraktLists).mockImplementation((nextSignal) => {
      signal = nextSignal;
      return new Promise(() => undefined);
    });

    await renderPanel();
    await vi.waitFor(() => expect(signal).toBeDefined());

    act(() => root.render(<></>));

    expect(signal?.aborted).toBe(true);
  });

  it("keeps the source draft when saving fails", async () => {
    vi.mocked(getTraktLists).mockResolvedValue({ success: true, lists: [] });
    vi.mocked(saveCollectionSourceInventory).mockRejectedValue(
      new Error("Salvataggio fonte non riuscito"),
    );
    await renderPanel();
    const name = container.querySelector<HTMLInputElement>("#collection-source-name");
    const value = container.querySelector<HTMLInputElement>("#collection-source-value");
    const form = container.querySelector<HTMLFormElement>(".collection-source-add");
    expect(name).not.toBeNull();
    expect(value).not.toBeNull();
    expect(form).not.toBeNull();

    act(() => {
      if (!name || !value) return;
      const setValue = Object.getOwnPropertyDescriptor(
        HTMLInputElement.prototype,
        "value",
      )?.set;
      setValue?.call(name, "Cinema personale");
      name.dispatchEvent(new Event("input", { bubbles: true }));
      setValue?.call(value, "https://trakt.tv/users/example/lists/cinema");
      value.dispatchEvent(new Event("input", { bubbles: true }));
    });
    await act(async () => {
      form?.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }));
      await Promise.resolve();
    });
    expect(saveCollectionSourceInventory).toHaveBeenCalledOnce();
    await act(async () => {
      await vi.waitFor(() => {
        expect(container.textContent).toContain("Salvataggio fonte non riuscito");
      });
    });

    expect(name?.value).toBe("Cinema personale");
    expect(value?.value).toBe("https://trakt.tv/users/example/lists/cinema");
  });
});
