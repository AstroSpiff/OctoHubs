// @vitest-environment jsdom

import { act } from "react";
import { createRoot } from "react-dom/client";
import { renderToStaticMarkup } from "react-dom/server";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import { LibraryOrderDialog } from "@/features/libraries/components/library-order-dialog";

const groups = [
  {
    group_name: "Cinema",
    collection_type: "movies",
    servers: ["green"],
    libraries: [{ server_id: "green", library_id: "films", library_name: "Film" }],
  },
  {
    group_name: "Serie",
    collection_type: "movies",
    servers: ["purple"],
    libraries: [{ server_id: "purple", library_id: "series", library_name: "Serie" }],
  },
];

const servers = [
  { id: "green", name: "Green" },
  { id: "purple", name: "Purple" },
];

declare global {
  var IS_REACT_ACT_ENVIRONMENT: boolean | undefined;
}

describe("LibraryOrderDialog", () => {
  it("locks both ordering drafts while either order is being saved", () => {
    const markup = renderToStaticMarkup(
      <LibraryOrderDialog
        open
        ready
        groups={groups}
        servers={servers}
        savingGroups
        savingServers={false}
        onClose={() => undefined}
        onSaveGroupOrder={async () => undefined}
        onSaveServerOrder={async () => undefined}
      />,
    );

    expect(markup).toContain('aria-busy="true"');
    expect(markup).toContain("Salvataggio ordine in corso...");
    expect(markup.match(/<button[^>]*\sdisabled(?:=|\s|>)/g)).toHaveLength(12);
  });

  it("shows a loading state instead of a false empty order before its data arrives", () => {
    const markup = renderToStaticMarkup(
      <LibraryOrderDialog
        open
        ready={false}
        groups={groups}
        servers={servers}
        savingGroups={false}
        savingServers={false}
        onClose={() => undefined}
        onSaveGroupOrder={async () => undefined}
        onSaveServerOrder={async () => undefined}
      />,
    );

    expect(markup).toContain("Caricamento ordine librerie e server...");
    expect(markup).not.toContain("Nessun gruppo disponibile.");
    expect(markup).not.toContain("Nessun server abilitato.");
  });
});

describe("LibraryOrderDialog draft refresh", () => {
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

  function render(currentGroups: typeof groups) {
    act(() => {
      root.render(
        <LibraryOrderDialog
          open
          ready
          groups={currentGroups}
          servers={servers}
          savingGroups={false}
          savingServers={false}
          onClose={() => undefined}
          onSaveGroupOrder={async () => undefined}
          onSaveServerOrder={async () => undefined}
        />,
      );
    });
  }

  function firstGroupLabel() {
    return container.querySelector("fieldset.library-order-list strong")
      ?.textContent;
  }

  it("keeps a local group order while the saved order refreshes", () => {
    render(groups);
    act(() => {
      container
        .querySelector<HTMLButtonElement>('[aria-label="Sposta Cinema in basso"]')
        ?.click();
    });
    expect(firstGroupLabel()).toContain("Serie");

    render(groups);

    expect(firstGroupLabel()).toContain("Serie");
  });

  it("adopts a refreshed group order while there are no local changes", () => {
    render(groups);
    render([...groups].reverse());

    expect(firstGroupLabel()).toContain("Serie");
  });
});
