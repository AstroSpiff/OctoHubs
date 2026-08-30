// @vitest-environment jsdom

import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/features/navigation/tab-order-api", () => ({
  getTabOrder: vi.fn(),
  saveTabOrder: vi.fn(),
}));

import { getTabOrder, saveTabOrder } from "@/features/navigation/tab-order-api";
import { usePersistedTabOrder } from "@/features/navigation/use-persisted-tab-order";

declare global {
  var IS_REACT_ACT_ENVIRONMENT: boolean | undefined;
}

const tabs = [
  { id: "first", label: "Prima" },
  { id: "second", label: "Seconda" },
  { id: "third", label: "Terza" },
] as const;

function ReorderHarness() {
  const tabOrder = usePersistedTabOrder({ page: "primary", tabs });

  return (
    <div data-order={tabOrder.order.join("|")}>
      {tabOrder.order.map((id) => (
        <button key={id} type="button" data-tab-id={id} {...tabOrder.interaction(id)}>{id}</button>
      ))}
    </div>
  );
}

describe("usePersistedTabOrder", () => {
  let container: HTMLDivElement;
  let root: ReturnType<typeof createRoot>;

  beforeEach(async () => {
    globalThis.IS_REACT_ACT_ENVIRONMENT = true;
    container = document.createElement("div");
    document.body.append(container);
    root = createRoot(container);
    vi.mocked(getTabOrder).mockResolvedValue([]);
    vi.mocked(saveTabOrder).mockImplementation(async (_page, order) => ({ success: true, order }));

    await act(async () => {
      root.render(<ReorderHarness />);
      await Promise.resolve();
    });
  });

  afterEach(() => {
    act(() => root.unmount());
    container.remove();
    vi.clearAllMocks();
    globalThis.IS_REACT_ACT_ENVIRONMENT = undefined;
  });

  it("saves a previewed drag order even when dragend occurs outside a drop target", async () => {
    const first = container.querySelector('[data-tab-id="first"]') as HTMLButtonElement;
    const second = container.querySelector('[data-tab-id="second"]') as HTMLButtonElement;
    const dataTransfer = { dropEffect: "", effectAllowed: "", setData: vi.fn() };

    await act(async () => {
      const dragStart = new Event("dragstart", { bubbles: true, cancelable: true });
      Object.defineProperty(dragStart, "dataTransfer", { value: dataTransfer });
      first.dispatchEvent(dragStart);

      const dragOver = new MouseEvent("dragover", { bubbles: true, cancelable: true, clientX: 10 });
      Object.defineProperty(dragOver, "dataTransfer", { value: dataTransfer });
      second.dispatchEvent(dragOver);

      first.dispatchEvent(new Event("dragend", { bubbles: true }));
      await Promise.resolve();
    });

    expect(container.firstElementChild?.getAttribute("data-order")).toBe("second|first|third");
    expect(saveTabOrder).toHaveBeenCalledWith("primary", [
      { tab_key: "second", position: 0 },
      { tab_key: "first", position: 1 },
      { tab_key: "third", position: 2 },
    ]);
  });
});
