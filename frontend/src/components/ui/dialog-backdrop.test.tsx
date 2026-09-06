// @vitest-environment jsdom

import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import { DialogBackdrop } from "@/components/ui/dialog-backdrop";


describe("DialogBackdrop focus trap", () => {
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

  it("keeps Tab inside the dialog when every control becomes disabled", async () => {
    act(() => root.render(
      <DialogBackdrop className="test-dialog" onDismiss={() => undefined}>
        <div role="dialog" aria-modal="true"><button type="button">Salva</button></div>
      </DialogBackdrop>,
    ));
    await act(async () => Promise.resolve());
    const button = container.querySelector("button")!;
    button.focus();
    button.disabled = true;

    const event = new KeyboardEvent("keydown", { key: "Tab", bubbles: true, cancelable: true });
    document.dispatchEvent(event);

    expect(event.defaultPrevented).toBe(true);
    expect(document.activeElement).toBe(container.querySelector('[role="dialog"]'));
  });
});
