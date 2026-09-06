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
    sourcesOpen = false,
    overrides: {
      sourcesDirty?: boolean;
      saving?: boolean;
      onClose?: () => void;
      onCloseSources?: () => void;
      onSave?: CollectionEditorDialogPropsForTest["onSave"];
    } = {},
  ) {
    act(() => {
      root.render(
        <QueryClientProvider client={queryClient}>
          <CollectionEditorDialog
            collection={current}
            options={options}
            saving={overrides.saving || false}
            sourceSelection={sourceSelection}
            onClose={overrides.onClose || vi.fn()}
            onOpenSources={vi.fn()}
            onCloseSources={overrides.onCloseSources || vi.fn()}
            sourcesOpen={sourcesOpen}
            sourcesDirty={overrides.sourcesDirty}
            onSelectSource={vi.fn()}
            onDirtyChange={vi.fn()}
            onSourcesDirtyChange={vi.fn()}
            onSave={overrides.onSave || vi.fn().mockResolvedValue(undefined)}
            onRemoveImage={vi.fn().mockResolvedValue(undefined)}
          />
        </QueryClientProvider>,
      );
    });
  }

  type CollectionEditorDialogPropsForTest = React.ComponentProps<
    typeof CollectionEditorDialog
  >;

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

  it("keeps one source-panel draft while the mobile surface opens", () => {
    Object.defineProperty(window, "matchMedia", {
      configurable: true,
      value: vi.fn().mockReturnValue({
        matches: true,
        addEventListener: vi.fn(),
        removeEventListener: vi.fn(),
      }),
    });
    render(collection(), null, false);
    const sourceName = container.querySelector<HTMLInputElement>(
      "#collection-source-name",
    );
    expect(sourceName).not.toBeNull();
    act(() => {
      if (!sourceName) return;
      const setValue = Object.getOwnPropertyDescriptor(
        HTMLInputElement.prototype,
        "value",
      )?.set;
      setValue?.call(sourceName, "Bozza locale");
      sourceName.dispatchEvent(new Event("input", { bubbles: true }));
    });

    render(collection(), null, true);

    expect(container.querySelectorAll("#collection-source-name")).toHaveLength(1);
    expect(
      container.querySelector<HTMLInputElement>("#collection-source-name")?.value,
    ).toBe("Bozza locale");
    expect(
      container.querySelector(".collection-editor-sources--mobile-open"),
    ).not.toBeNull();
  });

  it("asks before closing when only the source draft is dirty", () => {
    const onClose = vi.fn();
    render(collection(), null, false, { sourcesDirty: true, onClose });

    const cancel = Array.from(container.querySelectorAll("button")).find(
      (button) => button.textContent?.includes("Annulla"),
    );
    act(() => cancel?.click());

    expect(onClose).not.toHaveBeenCalled();
    expect(document.body.textContent).toContain("Modifiche non salvate");
  });

  it("does not save or discard a pending source-inventory draft", async () => {
    const onSave = vi.fn().mockResolvedValue(undefined);
    const onClose = vi.fn();
    render(collection(), null, false, {
      sourcesDirty: true,
      onSave,
      onClose,
    });

    const save = Array.from(container.querySelectorAll("button")).find(
      (button) => button.textContent?.includes("Salva collezione"),
    );
    await act(async () => save?.click());

    expect(onSave).not.toHaveBeenCalled();
    expect(onClose).not.toHaveBeenCalled();
    expect(container.textContent).toContain("Salva o svuota prima la bozza della fonte");
  });

  it("disables source inventory interactions while the collection is saving", () => {
    render(collection(), null, false, { saving: true });

    expect(container.querySelector<HTMLInputElement>("#collection-source-name")?.disabled).toBe(true);
    expect(container.querySelector<HTMLButtonElement>('[aria-label="Aggiorna liste salvate"]')?.disabled).toBe(true);
  });

  it("keeps the editor open when its draft changes during an in-flight save", async () => {
    let finishSave!: () => void;
    const onSave = vi.fn(() => new Promise<void>((resolve) => { finishSave = resolve; }));
    const onClose = vi.fn();
    render(collection(), null, false, { onSave, onClose });
    const save = Array.from(container.querySelectorAll("button")).find(
      (button) => button.textContent?.includes("Salva collezione"),
    );

    act(() => save?.click());
    await vi.waitFor(() => expect(onSave).toHaveBeenCalledOnce());
    render(collection(), {
      sourceType: "trakt",
      sourceValue: "changed-during-save",
      sourceOrigin: "personal",
    }, false, { onSave, onClose });
    await act(async () => {
      finishSave();
      await Promise.resolve();
    });

    expect(onClose).not.toHaveBeenCalled();
    expect(container.textContent).toContain("restano aperte");
    expect(coreInputs()[2]?.value).toBe("changed-during-save");
  });

  it("keeps mobile focus inside sources and Escape closes only that overlay", () => {
    Object.defineProperty(window, "matchMedia", {
      configurable: true,
      value: vi.fn().mockReturnValue({
        matches: true,
        addEventListener: vi.fn(),
        removeEventListener: vi.fn(),
      }),
    });
    const onClose = vi.fn();
    const onCloseSources = vi.fn();
    render(collection(), null, true, { onClose, onCloseSources });

    const sourceClose = container.querySelector<HTMLButtonElement>(
      '[aria-label="Chiudi fonti"]',
    );
    const form = container.querySelector(".collection-editor-form");
    expect(document.activeElement).toBe(sourceClose);
    expect(form?.hasAttribute("inert")).toBe(true);

    act(() => {
      container
        .querySelector(".collection-editor-sources")
        ?.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape", bubbles: true }));
    });

    expect(onCloseSources).toHaveBeenCalledOnce();
    expect(onClose).not.toHaveBeenCalled();
  });
});
