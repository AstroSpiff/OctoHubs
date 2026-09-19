// @vitest-environment jsdom
import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { useProbeContextSelection } from "@/features/probe/use-probe-context-selection";
import {
  probeLibraryServerStorageKey,
  probeRecentServerStorageKey,
} from "@/features/probe/probe-context-preferences";

declare global {
  var IS_REACT_ACT_ENVIRONMENT: boolean | undefined;
}

describe("useProbeContextSelection", () => {
  let container: HTMLDivElement;
  let root: ReturnType<typeof createRoot>;
  let latest: ReturnType<typeof useProbeContextSelection> | undefined;

  beforeEach(() => {
    globalThis.IS_REACT_ACT_ENVIRONMENT = true;
    window.localStorage.clear();
    container = document.createElement("div");
    document.body.appendChild(container);
    root = createRoot(container);
  });

  afterEach(() => {
    act(() => root.unmount());
    container.remove();
    globalThis.IS_REACT_ACT_ENVIRONMENT = undefined;
  });

  it("asks before changing the libraries server when a draft may be dirty", async () => {
    const confirm = vi.fn().mockResolvedValue(false);

    function Harness() {
      latest = useProbeContextSelection({
        servers: [
          { id: "green", name: "Green" },
          { id: "blue", name: "Blue" },
        ],
        confirmDiscardRecentConfigDraft: confirm,
        scope: "libraries",
      });
      return null;
    }

    await act(async () => root.render(<Harness />));
    expect(latest?.libraryServerId).toBe("green");
    expect(window.localStorage.getItem(probeLibraryServerStorageKey)).toBe("green");

    await act(async () => {
      expect(await latest?.selectLibraryServer("blue")).toBe(false);
    });

    expect(confirm).toHaveBeenCalledOnce();
    expect(latest?.libraryServerId).toBe("green");
  });

  it("restores the distinct recent and libraries server selections", async () => {
    window.localStorage.setItem(probeLibraryServerStorageKey, "blue");
    window.localStorage.setItem(probeRecentServerStorageKey, "green");

    function Harness() {
      latest = useProbeContextSelection({
        servers: [
          { id: "green", name: "Green" },
          { id: "blue", name: "Blue" },
        ],
        confirmDiscardRecentConfigDraft: vi.fn().mockResolvedValue(true),
        scope: "recent",
      });
      return null;
    }

    await act(async () => root.render(<Harness />));

    expect(latest?.libraryServerId).toBe("blue");
    expect(latest?.recentServerId).toBe("green");
  });

  it("keeps the recent all-servers choice across remounts", async () => {
    const confirm = vi.fn().mockResolvedValue(true);

    function Harness() {
      latest = useProbeContextSelection({
        servers: [{ id: "green", name: "Green" }],
        confirmDiscardRecentConfigDraft: confirm,
        scope: "recent",
      });
      return null;
    }

    await act(async () => root.render(<Harness />));
    await act(async () => {
      expect(await latest?.selectRecentServer("green")).toBe(true);
    });
    await act(async () => {
      expect(await latest?.selectRecentServer("all")).toBe(true);
    });

    expect(window.localStorage.getItem(probeRecentServerStorageKey)).toBe("all");
  });

  it("replaces a removed persisted server only after servers are available", async () => {
    window.localStorage.setItem(probeLibraryServerStorageKey, "removed");
    let servers: Array<{ id: string; name: string }> = [];

    function Harness() {
      latest = useProbeContextSelection({
        servers,
        confirmDiscardRecentConfigDraft: vi.fn().mockResolvedValue(true),
        scope: "libraries",
      });
      return null;
    }

    await act(async () => root.render(<Harness />));
    expect(latest?.libraryServerId).toBe("removed");
    expect(latest?.targetIds).toEqual([]);
    expect(window.localStorage.getItem(probeLibraryServerStorageKey)).toBe("removed");

    servers = [{ id: "green", name: "Green" }];
    await act(async () => root.render(<Harness />));

    expect(latest?.libraryServerId).toBe("green");
    expect(latest?.targetIds).toEqual(["green"]);
    expect(window.localStorage.getItem(probeLibraryServerStorageKey)).toBe("green");
  });
});
