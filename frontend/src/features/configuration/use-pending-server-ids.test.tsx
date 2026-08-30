// @vitest-environment jsdom

import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import { usePendingServerIds } from "@/features/configuration/use-pending-server-ids";

let latest: ReturnType<typeof usePendingServerIds> | undefined;

function Harness() {
  latest = usePendingServerIds();
  return null;
}

describe("usePendingServerIds", () => {
  let container: HTMLDivElement;
  let root: ReturnType<typeof createRoot>;

  beforeEach(() => {
    globalThis.IS_REACT_ACT_ENVIRONMENT = true;
    latest = undefined;
    container = document.createElement("div");
    document.body.append(container);
    root = createRoot(container);
    act(() => root.render(<Harness />));
  });

  afterEach(() => {
    act(() => root.unmount());
    container.remove();
    globalThis.IS_REACT_ACT_ENVIRONMENT = undefined;
  });

  it("tracks each server independently while concurrent mutations are pending", () => {
    act(() => {
      expect(latest?.begin("green")).toBe(true);
      expect(latest?.begin("purple")).toBe(true);
      expect(latest?.begin("green")).toBe(false);
    });

    expect(latest?.pendingIds).toEqual(new Set(["green", "purple"]));

    act(() => latest?.finish("green"));

    expect(latest?.pendingIds).toEqual(new Set(["purple"]));
  });
});
