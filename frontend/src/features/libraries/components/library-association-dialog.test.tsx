// @vitest-environment jsdom

import { act } from "react";
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

  function render(associations: LibraryAssociation[]) {
    act(() => {
      root.render(
        <LibraryAssociationDialog
          open
          ready
          groups={groups}
          associations={associations}
          saving={false}
          onClose={vi.fn()}
          onSave={vi.fn().mockResolvedValue(undefined)}
        />,
      );
    });
  }

  function associationInput() {
    return container.querySelector<HTMLInputElement>(
      '[aria-label^="Gruppo manuale"]',
    );
  }

  it("preserves a local association draft during an external refresh", () => {
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
});
