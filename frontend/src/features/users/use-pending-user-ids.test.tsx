// @vitest-environment jsdom

import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import { usePendingIds } from "@/features/users/use-pending-group-ids";

let latest: ReturnType<typeof usePendingIds> | undefined;

function Harness() {
  latest = usePendingIds();
  return null;
}

describe("user mutation pending identities", () => {
  let container: HTMLDivElement;
  let root: ReturnType<typeof createRoot>;

  beforeEach(() => {
    globalThis.IS_REACT_ACT_ENVIRONMENT = true;
    container = document.createElement("div");
    document.body.append(container);
    root = createRoot(container);
    act(() => root.render(<Harness />));
  });

  afterEach(() => {
    act(() => root.unmount());
    container.remove();
    latest = undefined;
    globalThis.IS_REACT_ACT_ENVIRONMENT = undefined;
  });

  it("blocks a second A mutation while allowing B to proceed", () => {
    act(() => {
      expect(latest?.begin("server-a:user-a")).toBe(true);
      expect(latest?.begin("server-a:user-b")).toBe(true);
      expect(latest?.begin("server-a:user-a")).toBe(false);
    });

    expect(latest?.pendingIds).toEqual(
      new Set(["server-a:user-a", "server-a:user-b"]),
    );

    act(() => latest?.finish("server-a:user-a"));
    act(() => {
      expect(latest?.begin("server-a:user-a")).toBe(true);
    });
  });
});
