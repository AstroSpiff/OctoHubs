// @vitest-environment jsdom

import { act } from "react";
import { readFileSync } from "node:fs";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { LibraryAssociationDialog } from "@/features/libraries/components/library-association-dialog";
import type {
  LibraryAssociation,
  LibraryGroup,
} from "@/features/libraries/types";

declare global {
  var IS_REACT_ACT_ENVIRONMENT: boolean | undefined;
}

const groups: LibraryGroup[] = [
  {
    group_name: "Film",
    collection_type: "movies",
    servers: ["green"],
    libraries: [
      {
        id: "movies",
        library_id: "movies",
        library_name: "Film",
        server_id: "green",
        server_name: "Green",
      },
    ],
  },
];

describe("LibraryAssociationDialog", () => {
  let container: HTMLDivElement;
  let root: ReturnType<typeof createRoot>;

  beforeEach(() => {
    globalThis.IS_REACT_ACT_ENVIRONMENT = true;
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
    associations: LibraryAssociation[],
    {
      open = true,
      ready = true,
      groups: nextGroups = groups,
      loadError = null,
      onClose = vi.fn(),
      onSave = vi.fn().mockResolvedValue(undefined),
    }: {
      open?: boolean;
      ready?: boolean;
      groups?: LibraryGroup[];
      loadError?: Error | null;
      onClose?: ReturnType<typeof vi.fn>;
      onSave?: ReturnType<typeof vi.fn>;
    } = {},
  ) {
    act(() => {
      root.render(
        <LibraryAssociationDialog
          open={open}
          ready={ready}
          groups={nextGroups}
          associations={associations}
          saving={false}
          loadError={loadError}
          onRetry={vi.fn()}
          onClose={onClose}
          onSave={onSave}
        />,
      );
    });
    return onSave;
  }

  function associationInput() {
    return container.querySelector<HTMLInputElement>(
      '[aria-label^="Gruppo manuale"]',
    );
  }

  it("preserves a local association draft when an older refresh resolves late", () => {
    render([{ server_id: "green", library_id: "movies", group_name: "Cinema" }]);
    const input = associationInput();
    expect(input?.value).toBe("Cinema");

    act(() => {
      const setValue = Object.getOwnPropertyDescriptor(
        HTMLInputElement.prototype,
        "value",
      )?.set;
      setValue?.call(input, "Bozza locale");
      input?.dispatchEvent(new Event("input", { bubbles: true }));
    });
    render([{ server_id: "green", library_id: "movies", group_name: "Serie" }]);

    expect(associationInput()?.value).toBe("Bozza locale");
  });

  it("adopts an external association refresh when the dialog is unchanged", () => {
    render([{ server_id: "green", library_id: "movies", group_name: "Cinema" }]);
    render([{ server_id: "green", library_id: "movies", group_name: "Serie" }]);

    expect(associationInput()?.value).toBe("Serie");
  });

  it("keeps an unresolved snapshot inert and cannot submit an empty replacement", () => {
    const onSave = render([], { ready: false, groups });
    const form = container.querySelector<HTMLFormElement>("form");

    expect(container.textContent).toContain("Caricamento associazioni librerie");
    expect(container.textContent).not.toContain("Nessuna libreria");
    expect(container.textContent).not.toContain("Salva associazioni");
    expect(associationInput()).toBeNull();

    act(() => {
      form?.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }));
    });
    expect(onSave).not.toHaveBeenCalled();
  });

  it("shows a retryable load error without exposing association controls", () => {
    render([], {
      ready: false,
      groups,
      loadError: new Error("Associazioni non disponibili"),
    });

    expect(container.textContent).toContain("Associazioni non disponibili");
    expect(container.textContent).toContain("Riprova");
    expect(container.textContent).not.toContain("Salva associazioni");
    expect(associationInput()).toBeNull();
  });

  it("allows an intentional success-empty snapshot to save an empty replacement", async () => {
    const onSave = render([], { groups: [] });
    const form = container.querySelector<HTMLFormElement>("form");

    expect(container.textContent).toContain("Nessuna libreria");
    expect(container.textContent).toContain("Salva associazioni");

    await act(async () => {
      form?.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }));
      await Promise.resolve();
    });

    expect(onSave).toHaveBeenCalledWith([]);
  });

  it("discards the previous opening draft and hydrates a fresh snapshot on reopen", () => {
    render([{ server_id: "green", library_id: "movies", group_name: "Cinema" }]);
    const input = associationInput();
    act(() => {
      const setValue = Object.getOwnPropertyDescriptor(
        HTMLInputElement.prototype,
        "value",
      )?.set;
      setValue?.call(input, "Bozza locale");
      input?.dispatchEvent(new Event("input", { bubbles: true }));
    });

    render([], { open: false });
    render([{ server_id: "green", library_id: "movies", group_name: "Serie" }]);

    expect(associationInput()?.value).toBe("Serie");
  });

  it("does not let the page open the dialog before both snapshots exist", () => {
    const source = readFileSync(
      "src/pages/libraries-page.tsx",
      "utf8",
    );

    expect(source).toContain("disabled={!associationsReady}");
    expect(source).toContain("ready={associationsReady}");
    expect(source).toContain("libraries.groups.data && libraries.associations.data");
  });
});
