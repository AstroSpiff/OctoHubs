// @vitest-environment jsdom

import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { OperationsCenterView } from "@/features/operations/components/operations-center-view";
import type { Operation } from "@/features/operations/types";
import { WorkspaceCapabilitiesProvider } from "@/features/session/workspace-capabilities";

declare global {
  var IS_REACT_ACT_ENVIRONMENT: boolean | undefined;
}

describe("OperationsCenterView", () => {
  let container: HTMLDivElement;
  let root: ReturnType<typeof createRoot>;

  beforeEach(() => {
    globalThis.IS_REACT_ACT_ENVIRONMENT = true;
    window.localStorage.clear();
    container = document.createElement("div");
    document.body.append(container);
    root = createRoot(container);
  });

  afterEach(() => {
    act(() => root.unmount());
    container.remove();
    globalThis.IS_REACT_ACT_ENVIRONMENT = undefined;
  });

  it("shows a query error and retry action even without cached operations", () => {
    const refresh = vi.fn();
    act(() => {
      root.render(
        <OperationsCenterView
          operations={[]}
          activeCount={0}
          fetching={false}
          error={new Error("Database non disponibile")}
          onRefresh={refresh}
          onClear={vi.fn()}
          storageKey="test.operations.open"
          label="Operazioni test"
        />,
      );
    });

    expect(container.querySelector('[role="alert"]')?.textContent).toContain(
      "Database non disponibile",
    );
    const retry = container.querySelector<HTMLButtonElement>(
      '[aria-label="Aggiorna operazioni test"]',
    );
    expect(retry).not.toBeNull();
    act(() => retry?.click());
    expect(refresh).toHaveBeenCalledOnce();
  });

  it("lets the user collapse an error-only panel after auto-opening it", () => {
    act(() => {
      root.render(
        <OperationsCenterView
          operations={[]}
          activeCount={0}
          fetching={false}
          error={new Error("Database non disponibile")}
          onRefresh={vi.fn()}
          onClear={vi.fn()}
          storageKey="test.operations.collapse"
          label="Operazioni test"
        />,
      );
    });

    const collapse = container.querySelector<HTMLButtonElement>(
      '[aria-label="Riduci operazioni test"]',
    );
    expect(collapse).not.toBeNull();
    act(() => collapse?.click());

    expect(container.querySelector(".operations-center-panel")).toBeNull();
    expect(
      container.querySelector(".operations-center-toggle")?.getAttribute("aria-expanded"),
    ).toBe("false");
  });

  it("keeps operation state visible but hides mutating controls from viewers", () => {
    window.localStorage.setItem("test.operations.viewer", "true");
    const base: Operation = {
      id: "completed",
      kind: "workflow",
      title: "Sincronizzazione",
      summary: "Server A",
      status: "success",
      message: "Completata",
      progress: 100,
      current: 1,
      total: 1,
      details: {},
      error: null,
      started_at: "2026-09-01T12:00:00Z",
      updated_at: "2026-09-01T12:01:00Z",
      finished_at: "2026-09-01T12:01:00Z",
    };
    const running: Operation = {
      ...base,
      id: "running",
      status: "running",
      progress: 25,
      details: { can_stop: true },
      finished_at: null,
    };
    act(() => {
      root.render(
        <WorkspaceCapabilitiesProvider canMutate={false}>
          <OperationsCenterView
            operations={[running, base]}
            activeCount={1}
            fetching={false}
            onRefresh={vi.fn()}
            onClear={vi.fn()}
            onStop={vi.fn()}
            storageKey="test.operations.viewer"
            label="Operazioni utenti"
          />
        </WorkspaceCapabilitiesProvider>,
      );
    });

    expect(container.textContent).toContain("Sincronizzazione");
    expect(container.querySelector('[aria-label="Pulisci operazioni completate"]')).toBeNull();
    expect(container.querySelector('[aria-label="Interrompi Sincronizzazione"]')).toBeNull();
    expect(container.querySelector('[aria-label="Aggiorna operazioni utenti"]')).not.toBeNull();
  });

  it("shows clear and stop controls to editors", () => {
    window.localStorage.setItem("test.operations.editor", "true");
    const operation: Operation = {
      id: "running",
      kind: "workflow",
      title: "Sincronizzazione",
      summary: "Server A",
      status: "running",
      message: "In corso",
      progress: 25,
      current: 1,
      total: 4,
      details: { can_stop: true },
      error: null,
      started_at: "2026-09-01T12:00:00Z",
      updated_at: "2026-09-01T12:01:00Z",
      finished_at: null,
    };
    const completed = { ...operation, id: "completed", status: "success" as const };
    act(() => {
      root.render(
        <WorkspaceCapabilitiesProvider canMutate>
          <OperationsCenterView
            operations={[operation, completed]}
            activeCount={1}
            fetching={false}
            onRefresh={vi.fn()}
            onClear={vi.fn()}
            onStop={vi.fn()}
            storageKey="test.operations.editor"
            label="Operazioni utenti"
          />
        </WorkspaceCapabilitiesProvider>,
      );
    });

    expect(container.querySelector('[aria-label="Pulisci operazioni completate"]')).not.toBeNull();
    expect(container.querySelector('[aria-label="Interrompi Sincronizzazione"]')).not.toBeNull();
  });
});
