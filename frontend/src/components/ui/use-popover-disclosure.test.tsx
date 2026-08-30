// @vitest-environment jsdom

import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { usePopoverDisclosure } from "@/components/ui/use-popover-disclosure";

declare global {
  var IS_REACT_ACT_ENVIRONMENT: boolean | undefined;
}

function TestPopover() {
  const popover = usePopoverDisclosure();

  return (
    <>
      <button type="button">Fuori dal menu</button>
      <details ref={popover.detailsRef} onToggle={popover.onToggle}>
        <summary
          ref={popover.summaryRef}
          aria-controls={popover.contentId}
          aria-expanded={popover.open}
        >
          Azioni
        </summary>
        <div id={popover.contentId}>Pannello</div>
      </details>
    </>
  );
}

describe("usePopoverDisclosure", () => {
  let container: HTMLDivElement;
  let root: ReturnType<typeof createRoot>;

  beforeEach(() => {
    globalThis.IS_REACT_ACT_ENVIRONMENT = true;
    container = document.createElement("div");
    document.body.append(container);
    root = createRoot(container);
    vi.spyOn(window, "requestAnimationFrame").mockImplementation(
      (callback) => {
        callback(0);
        return 1;
      },
    );
    vi.spyOn(window, "cancelAnimationFrame").mockImplementation(() => undefined);
    act(() => root.render(<TestPopover />));
  });

  afterEach(() => {
    act(() => root.unmount());
    container.remove();
    vi.restoreAllMocks();
    globalThis.IS_REACT_ACT_ENVIRONMENT = undefined;
  });

  function openPopover() {
    const details = container.querySelector("details") as HTMLDetailsElement;
    act(() => {
      details.open = true;
      details.dispatchEvent(new Event("toggle", { bubbles: true }));
    });
    return details;
  }

  it("closes when the user continues outside the popover", () => {
    const details = openPopover();
    expect(details.open).toBe(true);

    act(() => {
      container.querySelector("button")?.dispatchEvent(
        new Event("pointerdown", { bubbles: true }),
      );
    });

    expect(details.open).toBe(false);
  });

  it("returns focus to the trigger when Escape closes the popover", () => {
    const details = openPopover();
    const trigger = container.querySelector("summary") as HTMLElement;

    act(() => {
      document.dispatchEvent(
        new KeyboardEvent("keydown", { bubbles: true, key: "Escape" }),
      );
    });

    expect(details.open).toBe(false);
    expect(document.activeElement).toBe(trigger);
  });
});
