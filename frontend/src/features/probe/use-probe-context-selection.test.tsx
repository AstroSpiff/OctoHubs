// @vitest-environment jsdom
import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { useProbeContextSelection } from "@/features/probe/use-probe-context-selection";

declare global {
  var IS_REACT_ACT_ENVIRONMENT: boolean | undefined;
}

describe("useProbeContextSelection", () => {
  let container: HTMLDivElement;
  let root: ReturnType<typeof createRoot>;
  let latest: ReturnType<typeof useProbeContextSelection> | undefined;

  beforeEach(() => {
    globalThis.IS_REACT_ACT_ENVIRONMENT = true;
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

    await act(async () => {
      expect(await latest?.selectLibraryServer("blue")).toBe(false);
    });

    expect(confirm).toHaveBeenCalledOnce();
    expect(latest?.libraryServerId).toBe("green");
  });
});
