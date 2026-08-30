// @vitest-environment jsdom

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { CollectionEditorDialog } from "@/features/collections/components/collection-editor-dialog";
import type {
  CollectionOptions,
  EmbyCollection,
} from "@/features/collections/types";

declare global {
  var IS_REACT_ACT_ENVIRONMENT: boolean | undefined;
}

const options: CollectionOptions = {
  success: true,
  source_types: [{ value: "trakt", label: "Trakt" }],
  servers: [{ id: "green", name: "Green" }],
  trakt_enabled: true,
  mdblist_enabled: true,
};

function collection(changes: Partial<EmbyCollection> = {}): EmbyCollection {
  return {
    id: "watchlist",
    name: "Watchlist",
    enabled: true,
    source_type: "trakt",
    source_value: "saved-list",
    server_ids: ["green"],
    ...changes,
  };
}

describe("CollectionEditorDialog", () => {
  let container: HTMLDivElement;
  let root: ReturnType<typeof createRoot>;
  let queryClient: QueryClient;

  beforeEach(() => {
    globalThis.IS_REACT_ACT_ENVIRONMENT = true;
    queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
    container = document.createElement("div");
    document.body.append(container);
    root = createRoot(container);
  });

  afterEach(() => {
    act(() => root.unmount());
    container.remove();
    globalThis.IS_REACT_ACT_ENVIRONMENT = undefined;
  });

  function render(
    current: EmbyCollection,
    sourceSelection?: {
      sourceType: string;
      sourceValue: string;
      sourceOrigin: "personal" | "inventory";
    } | null,
  ) {
    act(() => {
      root.render(
        <QueryClientProvider client={queryClient}>
          <CollectionEditorDialog
            collection={current}
            options={options}
            saving={false}
            sourceSelection={sourceSelection}
            onClose={vi.fn()}
            onOpenSources={vi.fn()}
            onSelectSource={vi.fn()}
            onDirtyChange={vi.fn()}
            onSourcesDirtyChange={vi.fn()}
            onSave={vi.fn().mockResolvedValue(undefined)}
            onRemoveImage={vi.fn().mockResolvedValue(undefined)}
          />
        </QueryClientProvider>,
      );
    });
  }

  function coreInputs() {
    return Array.from(
      container.querySelectorAll<HTMLInputElement>(
        ".collection-editor-fields input",
      ),
    );
  }

  it("preserves a local source selection while collection data refreshes", () => {
    const sourceSelection = {
      sourceType: "trakt",
      sourceValue: "local-list",
      sourceOrigin: "personal" as const,
    };
    render(collection());
    render(collection(), sourceSelection);

    expect(coreInputs()[2]?.value).toBe("local-list");

    render(
      collection({ name: "Nome aggiornato", source_value: "remote-list" }),
      sourceSelection,
    );

    expect(coreInputs()[0]?.value).toBe("Watchlist");
    expect(coreInputs()[2]?.value).toBe("local-list");
  });

  it("adopts refreshed collection data while the editor is unchanged", () => {
    render(collection());
    render(collection({ name: "Nome aggiornato" }));

    expect(coreInputs()[0]?.value).toBe("Nome aggiornato");
  });
});
