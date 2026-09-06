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

function ReorderHarness({ page = "primary", instance = "only" }: { page?: string; instance?: string }) {
  const tabOrder = usePersistedTabOrder({ page, tabs });

  return (
    <div data-instance={instance} data-order={tabOrder.order.join("|")}>
      {tabOrder.order.map((id) => (
        <button key={id} type="button" data-tab-id={id} {...tabOrder.interaction(id)}>{id}</button>
      ))}
      <span aria-live="polite">{tabOrder.announcement}</span>
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

  it("rolls back the optimistic order and announces a save failure", async () => {
    vi.mocked(saveTabOrder).mockRejectedValueOnce(new Error("offline"));
    await act(async () => {
      root.render(<ReorderHarness page="rollback-test" />);
      await Promise.resolve();
    });
    const first = container.querySelector('[data-tab-id="first"]') as HTMLButtonElement;

    await act(async () => {
      first.dispatchEvent(new KeyboardEvent("keydown", {
        altKey: true,
        bubbles: true,
        cancelable: true,
        key: "ArrowRight",
      }));
      await Promise.resolve();
      await Promise.resolve();
    });

    expect(container.firstElementChild?.getAttribute("data-order")).toBe("first|second|third");
    expect(container.querySelector("[aria-live='polite']")?.textContent).toBe(
      "Impossibile salvare l'ordine delle schede.",
    );
  });

  it("serializes saves for the same page across mounted navigation variants", async () => {
    let resolveFirstSave: ((value: { success: true; order: Array<{ tab_key: string; position: number }> }) => void) | undefined;
    const firstSave = new Promise<{ success: true; order: Array<{ tab_key: string; position: number }> }>((resolve) => {
      resolveFirstSave = resolve;
    });
    vi.mocked(saveTabOrder)
      .mockImplementationOnce(() => firstSave)
      .mockImplementationOnce(async (_page, order) => ({ success: true, order }));

    await act(async () => {
      root.render(<><ReorderHarness page="shared-queue-test" instance="sidebar" /><ReorderHarness page="shared-queue-test" instance="topbar" /></>);
      await Promise.resolve();
    });

    const sidebar = container.querySelector('[data-instance="sidebar"]') as HTMLElement;
    const topbar = container.querySelector('[data-instance="topbar"]') as HTMLElement;
    await act(async () => {
      (sidebar.querySelector('[data-tab-id="first"]') as HTMLButtonElement).dispatchEvent(new KeyboardEvent("keydown", {
        altKey: true,
        bubbles: true,
        cancelable: true,
        key: "ArrowRight",
      }));
      await Promise.resolve();
    });
    await act(async () => {
      (topbar.querySelector('[data-tab-id="first"]') as HTMLButtonElement).dispatchEvent(new KeyboardEvent("keydown", {
        altKey: true,
        bubbles: true,
        cancelable: true,
        key: "ArrowRight",
      }));
      await Promise.resolve();
    });

    expect(sidebar.getAttribute("data-order")).toBe("second|third|first");
    expect(topbar.getAttribute("data-order")).toBe("second|third|first");
    expect(saveTabOrder).toHaveBeenCalledTimes(1);

    await act(async () => {
      resolveFirstSave?.({
        success: true,
        order: [
          { tab_key: "second", position: 0 },
          { tab_key: "first", position: 1 },
          { tab_key: "third", position: 2 },
        ],
      });
      await firstSave;
      await Promise.resolve();
      await Promise.resolve();
    });

    expect(saveTabOrder).toHaveBeenCalledTimes(2);
    expect(vi.mocked(saveTabOrder).mock.calls).toEqual([
      ["shared-queue-test", [
        { tab_key: "second", position: 0 },
        { tab_key: "first", position: 1 },
        { tab_key: "third", position: 2 },
      ]],
      ["shared-queue-test", [
        { tab_key: "second", position: 0 },
        { tab_key: "third", position: 1 },
        { tab_key: "first", position: 2 },
      ]],
    ]);
  });
});
