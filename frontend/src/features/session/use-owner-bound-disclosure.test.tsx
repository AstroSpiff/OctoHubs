// @vitest-environment jsdom

import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import { useOwnerBoundDisclosure } from "@/features/session/use-owner-bound-disclosure";

declare global {
  var IS_REACT_ACT_ENVIRONMENT: boolean | undefined;
}

let disclosure: ReturnType<typeof useOwnerBoundDisclosure> | undefined;

function Harness({ ownerKey }: { ownerKey: string | null }) {
  disclosure = useOwnerBoundDisclosure(ownerKey);
  return disclosure.isOpen ? <div role="dialog">Preferenze</div> : null;
}

describe("owner-bound disclosure", () => {
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
    disclosure = undefined;
    globalThis.IS_REACT_ACT_ENVIRONMENT = undefined;
  });

  it("never reopens an A lease after A to B to A owner changes", async () => {
    await act(async () => root.render(<Harness ownerKey="id:1" />));
    act(() => disclosure?.open());
    expect(container.querySelector('[role="dialog"]')).not.toBeNull();

    await act(async () => root.render(<Harness ownerKey="id:2" />));
    expect(container.querySelector('[role="dialog"]')).toBeNull();
    await act(async () => root.render(<Harness ownerKey="id:1" />));

    expect(container.querySelector('[role="dialog"]')).toBeNull();
  });

  it("rejects a late open callback captured by the previous owner", async () => {
    await act(async () => root.render(<Harness ownerKey="id:1" />));
    const staleOpen = disclosure?.open;
    await act(async () => root.render(<Harness ownerKey="id:2" />));
    act(() => staleOpen?.());
    await act(async () => root.render(<Harness ownerKey="id:1" />));

    expect(container.querySelector('[role="dialog"]')).toBeNull();
  });
});
