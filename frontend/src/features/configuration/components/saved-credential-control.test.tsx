// @vitest-environment jsdom

import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { SavedCredentialControl } from "@/features/configuration/components/saved-credential-control";

declare global {
  var IS_REACT_ACT_ENVIRONMENT: boolean | undefined;
}

describe("SavedCredentialControl", () => {
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

  it("associates the visible removal text with its checkbox", async () => {
    const onChange = vi.fn();
    await act(async () => {
      root.render(
        <SavedCredentialControl
          configured
          pendingRemoval={false}
          label="Rimuovi password salvata"
          onPendingRemovalChange={onChange}
        />,
      );
    });

    act(() => container.querySelector("span")?.click());

    expect(onChange).toHaveBeenCalledWith(true);
    expect(container.querySelector("label")?.control).toBe(container.querySelector("input"));
  });
});
