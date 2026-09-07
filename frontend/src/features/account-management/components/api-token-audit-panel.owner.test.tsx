// @vitest-environment jsdom

import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ApiTokenAuditPanel } from "@/features/account-management/components/api-token-audit-panel";
import type { ApiTokenAuditFilters } from "@/features/account-management/types";
import { WorkspaceCapabilitiesProvider } from "@/features/session/workspace-capabilities";
import { setCsrfToken } from "@/lib/http";

declare global {
  var IS_REACT_ACT_ENVIRONMENT: boolean | undefined;
}

describe("ApiTokenAuditPanel owner lifecycle", () => {
  let container: HTMLDivElement;
  let root: ReturnType<typeof createRoot>;

  beforeEach(() => {
    globalThis.IS_REACT_ACT_ENVIRONMENT = true;
    container = document.createElement("div");
    document.body.append(container);
    root = createRoot(container);
    setCsrfToken("owner-a", 1);
  });

  afterEach(() => {
    act(() => root.unmount());
    container.remove();
    setCsrfToken("");
    vi.restoreAllMocks();
    globalThis.IS_REACT_ACT_ENVIRONMENT = undefined;
  });

  it("does not download an audit response that settles after A changes to B", async () => {
    let resolveExport: ((blob: Blob) => void) | undefined;
    let requestSignal: AbortSignal | undefined;
    const onExport = vi.fn((_filters: ApiTokenAuditFilters, signal?: AbortSignal) => {
      requestSignal = signal;
      return new Promise<Blob>((resolve) => {
        resolveExport = resolve;
      });
    });
    const createObjectUrl = vi.fn(() => "blob:audit");
    Object.defineProperty(URL, "createObjectURL", { configurable: true, value: createObjectUrl });
    const anchorClick = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => undefined);

    const renderForOwner = (accountId: number) => (
      <WorkspaceCapabilitiesProvider accountId={accountId} canMutate>
        <ApiTokenAuditPanel
          events={[]}
          filters={{}}
          loading={false}
          tokens={[]}
          onChangeFilters={() => undefined}
          onExport={onExport}
          onRefresh={() => undefined}
        />
      </WorkspaceCapabilitiesProvider>
    );
    await act(async () => root.render(renderForOwner(1)));
    act(() => [...container.querySelectorAll("button")]
      .find((button) => button.textContent?.includes("Esporta JSON"))
      ?.click());
    expect(onExport).toHaveBeenCalledOnce();

    setCsrfToken("owner-b", 2);
    await act(async () => root.render(renderForOwner(2)));
    expect(requestSignal?.aborted).toBe(true);

    await act(async () => {
      resolveExport?.(new Blob(["owner-a-audit"]));
      await Promise.resolve();
    });

    expect(createObjectUrl).not.toHaveBeenCalled();
    expect(anchorClick).not.toHaveBeenCalled();
  });
});
