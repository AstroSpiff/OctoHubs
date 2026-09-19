// @vitest-environment jsdom

import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { SearchResultActions } from "@/features/research/components/search-result-actions";
import { WorkspaceCapabilitiesProvider } from "@/features/session/workspace-capabilities";

const { sendToQbittorrent } = vi.hoisted(() => ({
  sendToQbittorrent: vi.fn(async () => ({ success: true, message: "Inviato" })),
}));

vi.mock("@/features/research/api", async (importOriginal) => ({
  ...await importOriginal<typeof import("@/features/research/api")>(),
  sendToQbittorrent,
}));

describe("manual torrent client selection", () => {
  let container: HTMLDivElement;
  let root: ReturnType<typeof createRoot>;

  beforeEach(() => {
    globalThis.IS_REACT_ACT_ENVIRONMENT = true;
    container = document.createElement("div");
    document.body.append(container);
    root = createRoot(container);
    sendToQbittorrent.mockClear();
  });

  afterEach(() => {
    act(() => root.unmount());
    container.remove();
    globalThis.IS_REACT_ACT_ENVIRONMENT = undefined;
  });

  it("asks for a destination when multiple clients are enabled", async () => {
    render([
      { id: "qb", name: "Casa", kind: "qbittorrent", is_default: true },
      { id: "deluge", name: "Seedbox", kind: "deluge", is_default: false },
    ]);

    act(() => button("Invia al client torrent").click());
    expect(document.querySelector('[role="dialog"]')?.textContent).toContain("Scegli il client torrent");

    await act(async () => {
      button("Seedbox", document).click();
      await Promise.resolve();
    });

    expect(sendToQbittorrent).toHaveBeenCalledWith("ohsdl_reference", "deluge");
    expect(document.querySelector('[role="dialog"]')).toBeNull();
  });

  it("sends directly when only one client is enabled", async () => {
    render([{ id: "transmission", name: "Transmission", kind: "transmission", is_default: true }]);

    await act(async () => {
      button("Invia al client torrent").click();
      await Promise.resolve();
    });

    expect(sendToQbittorrent).toHaveBeenCalledWith("ohsdl_reference", "transmission");
    expect(document.querySelector('[role="dialog"]')).toBeNull();
  });

  function render(torrentClients: Array<{ id: string; name: string; kind: "qbittorrent" | "deluge" | "transmission"; is_default: boolean }>) {
    act(() => root.render(
      <WorkspaceCapabilitiesProvider canMutate>
        <SearchResultActions
          result={{ title: "Example", torrent_ref: "ohsdl_reference" }}
          canSend
          torrentClients={torrentClients}
          onNotice={vi.fn()}
        />
      </WorkspaceCapabilitiesProvider>,
    ));
  }

  function button(label: string, scope: ParentNode = container): HTMLButtonElement {
    const result = [...scope.querySelectorAll<HTMLButtonElement>("button")]
      .find((item) => item.getAttribute("aria-label") === label || item.textContent?.includes(label));
    if (!result) throw new Error(`Button not found: ${label}`);
    return result;
  }
});
