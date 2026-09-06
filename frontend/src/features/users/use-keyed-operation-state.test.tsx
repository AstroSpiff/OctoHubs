// @vitest-environment jsdom

import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import { useKeyedOperationState } from "@/lib/use-keyed-operation-state";

declare global {
  var IS_REACT_ACT_ENVIRONMENT: boolean | undefined;
}

let latest: ReturnType<typeof useKeyedOperationState> | undefined;

function Harness() {
  latest = useKeyedOperationState();
  return null;
}

describe("useKeyedOperationState", () => {
  let container: HTMLDivElement;
  let root: ReturnType<typeof createRoot>;

  beforeEach(() => {
    globalThis.IS_REACT_ACT_ENVIRONMENT = true;
    latest = undefined;
    container = document.createElement("div");
    document.body.appendChild(container);
    root = createRoot(container);
    act(() => root.render(<Harness />));
  });

  afterEach(() => {
    act(() => root.unmount());
    container.remove();
    globalThis.IS_REACT_ACT_ENVIRONMENT = undefined;
  });

  it("keeps pending and failure state associated with each concurrent target", () => {
    act(() => {
      latest?.begin(["group-a"]);
      latest?.begin(["group-b"]);
    });
    act(() => {
      latest?.fail(["group-a"], new Error("A non riuscito"));
      latest?.finish(["group-a"]);
    });

    expect(latest?.pendingKeys.has("group-a")).toBe(false);
    expect(latest?.pendingKeys.has("group-b")).toBe(true);
    expect(latest?.errors).toEqual({ "group-a": "A non riuscito" });

    act(() => {
      latest?.begin(["group-a"]);
    });
    expect(latest?.errors).toEqual({});
  });
});
