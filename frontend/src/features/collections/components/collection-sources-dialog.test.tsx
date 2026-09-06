// @vitest-environment jsdom

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  getCollectionSourceInventory,
  getMdbListLists,
  getTraktLists,
  saveCollectionSourceInventory,
} from "@/features/collections/api";
import { CollectionSourcesDialog } from "@/features/collections/components/collection-sources-dialog";

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
  trakt_enabled: false,
  mdblist_enabled: false,
};

describe("CollectionSourcesDialog busy lifecycle", () => {
  let container: HTMLDivElement;
  let root: ReturnType<typeof createRoot>;
  let client: QueryClient;

  beforeEach(() => {
    globalThis.IS_REACT_ACT_ENVIRONMENT = true;
    vi.mocked(getCollectionSourceInventory).mockResolvedValue({
      success: true,
      items: [],
    });
    vi.mocked(getTraktLists).mockResolvedValue({ success: true, lists: [] });
    vi.mocked(getMdbListLists).mockResolvedValue({ success: true, lists: [] });
    client = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
    container = document.createElement("div");
    document.body.append(container);
    root = createRoot(container);
  });

  afterEach(() => {
    act(() => root.unmount());
    container.remove();
    client.clear();
    vi.resetAllMocks();
    globalThis.IS_REACT_ACT_ENVIRONMENT = undefined;
  });

  it("blocks every dismiss path while an inventory save is pending", async () => {
    const savedItem = {
      id: "cinema",
      name: "Cinema",
      source_type: "trakt_list",
      source_value: "example/cinema",
    };
    let resolveSave: ((value: {
      success: boolean;
      item: typeof savedItem;
      items: Array<typeof savedItem>;
    }) => void) | undefined;
    vi.mocked(saveCollectionSourceInventory).mockImplementation(
      () => new Promise((resolve) => { resolveSave = resolve; }),
    );
    const onClose = vi.fn();
    await act(async () => {
      root.render(
        <QueryClientProvider client={client}>
          <CollectionSourcesDialog
            open
            options={options}
            onClose={onClose}
            onSelect={vi.fn()}
          />
        </QueryClientProvider>,
      );
      await Promise.resolve();
    });

    const value = container.querySelector<HTMLInputElement>(
      "#collection-source-value",
    );
    const form = container.querySelector<HTMLFormElement>(
      ".collection-source-add",
    );
    const setValue = Object.getOwnPropertyDescriptor(
      HTMLInputElement.prototype,
      "value",
    )?.set;
    act(() => {
      setValue?.call(value, "https://trakt.tv/users/example/lists/cinema");
      value?.dispatchEvent(new Event("input", { bubbles: true }));
      form?.dispatchEvent(
        new Event("submit", { bubbles: true, cancelable: true }),
      );
    });

    const close = container.querySelector<HTMLButtonElement>(
      '[aria-label="Chiudi fonti collezioni"]',
    );
    await vi.waitFor(() => expect(close?.disabled).toBe(true));
    const backdrop = container.querySelector<HTMLElement>(
      "[data-octohubs-dialog-backdrop]",
    );
    act(() => {
      backdrop?.dispatchEvent(
        new MouseEvent("mousedown", { bubbles: true }),
      );
      document.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape" }));
    });
    expect(onClose).not.toHaveBeenCalled();

    await act(async () => {
      resolveSave?.({ success: true, item: savedItem, items: [savedItem] });
      await Promise.resolve();
    });
    await vi.waitFor(() => expect(close?.disabled).toBe(false));
  });
});
