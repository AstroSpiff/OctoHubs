// @vitest-environment jsdom

import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import { useKeyedOperationState } from "@/features/user-icons/use-keyed-operation-state";

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
    document.body.append(container);
    root = createRoot(container);
    act(() => root.render(<Harness />));
  });

  afterEach(() => {
    act(() => root.unmount());
    container.remove();
    globalThis.IS_REACT_ACT_ENVIRONMENT = undefined;
  });

  it("keeps concurrent keys and their errors independent", () => {
    act(() => {
      latest?.begin(["rule:family:green"]);
      latest?.begin(["rule:family:purple"]);
    });
    expect(latest?.pendingKeys).toEqual(new Set(["rule:family:green", "rule:family:purple"]));

    act(() => {
      latest?.fail(["rule:family:green"], new Error("Green non disponibile"));
      latest?.finish(["rule:family:green"]);
    });
    expect(latest?.pendingKeys).toEqual(new Set(["rule:family:purple"]));
    expect(latest?.errors).toEqual({ "rule:family:green": "Green non disponibile" });

    act(() => {
      latest?.begin(["rule:family:green"]);
    });
    expect(latest?.errors).toEqual({});
    expect(latest?.pendingKeys).toEqual(new Set(["rule:family:purple", "rule:family:green"]));
  });

  it("does not clear a key until all overlapping operations have settled", () => {
    act(() => {
      latest?.begin(["profile:family"]);
      latest?.begin(["profile:family"]);
      latest?.finish(["profile:family"]);
    });
    expect(latest?.pendingKeys).toEqual(new Set(["profile:family"]));

    act(() => latest?.finish(["profile:family"]));
    expect(latest?.pendingKeys).toEqual(new Set());
  });
});
