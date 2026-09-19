// @vitest-environment jsdom

import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { SearchResultActions } from "@/features/research/components/search-result-actions";
import type { SearchResult } from "@/features/research/types";
import { WorkspaceCapabilitiesProvider } from "@/features/session/workspace-capabilities";

const { sendToProwlarr } = vi.hoisted(() => ({
  sendToProwlarr: vi.fn(async () => ({ success: true, message: "Inviato" })),
}));

vi.mock("@/features/research/api", async (importOriginal) => ({
  ...await importOriginal<typeof import("@/features/research/api")>(),
  sendToProwlarr,
}));

describe("Prowlarr-owned torrent dispatch", () => {
  let container: HTMLDivElement;
  let root: ReturnType<typeof createRoot>;

  beforeEach(() => {
    globalThis.IS_REACT_ACT_ENVIRONMENT = true;
    container = document.createElement("div");
    document.body.append(container);
    root = createRoot(container);
    sendToProwlarr.mockClear();
  });

  afterEach(() => {
    act(() => root.unmount());
    container.remove();
    globalThis.IS_REACT_ACT_ENVIRONMENT = undefined;
  });

  it("delegates to Prowlarr even when local client profiles are retained", async () => {
    render([
      { id: "qb", name: "Casa", kind: "qbittorrent", is_default: true },
      { id: "deluge", name: "Seedbox", kind: "deluge", is_default: false },
    ]);

    await act(async () => {
      button("Invia tramite Prowlarr").click();
      await Promise.resolve();
    });

    expect(sendToProwlarr).toHaveBeenCalledWith("ohsgrab_reference");
    expect(document.querySelector('[role="dialog"]')).toBeNull();
  });

  it("does not offer dispatch for a direct Jackett result", () => {
    render([], { title: "Example", torrent_ref: "ohsdl_reference" });

    expect(container.querySelector('[aria-label="Invia tramite Prowlarr"]')).toBeNull();
    expect(sendToProwlarr).not.toHaveBeenCalled();
  });

  function render(
    torrentClients: Array<{ id: string; name: string; kind: "qbittorrent" | "deluge" | "transmission"; is_default: boolean }>,
    result: SearchResult = { title: "Example", prowlarr_grab_ref: "ohsgrab_reference" },
  ) {
    act(() => root.render(
      <WorkspaceCapabilitiesProvider canMutate>
        <SearchResultActions
          result={result}
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
