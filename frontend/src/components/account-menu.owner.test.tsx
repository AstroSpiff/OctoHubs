// @vitest-environment jsdom

import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { AccountMenu } from "@/components/account-menu";
import { logoutCurrentSession } from "@/features/account-management/api";
import { WorkspaceCapabilitiesProvider } from "@/features/session/workspace-capabilities";
import { navigateBrowser } from "@/lib/browser-download";
import { setCsrfToken } from "@/lib/http";

vi.mock("@/features/account-management/api", () => ({
  logoutCurrentSession: vi.fn(),
}));
vi.mock("@/lib/browser-download", () => ({
  navigateBrowser: vi.fn(),
}));

declare global {
  var IS_REACT_ACT_ENVIRONMENT: boolean | undefined;
}

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((next) => { resolve = next; });
  return { promise, resolve };
}

function Harness({ accountId }: { accountId: number }) {
  return (
    <WorkspaceCapabilitiesProvider accountId={accountId} canMutate>
      <AccountMenu
        key={accountId}
        roleLabel="Amministratore"
        theme="light"
        username={`owner-${accountId}`}
        onOpenPreferences={() => undefined}
        onToggleTheme={() => undefined}
      />
    </WorkspaceCapabilitiesProvider>
  );
}

describe("AccountMenu logout ownership", () => {
  let container: HTMLDivElement;
  let root: ReturnType<typeof createRoot>;

  beforeEach(() => {
    globalThis.IS_REACT_ACT_ENVIRONMENT = true;
    container = document.createElement("div");
    document.body.append(container);
    root = createRoot(container);
    setCsrfToken("csrf-a", 1);
  });

  afterEach(() => {
    act(() => root.unmount());
    container.remove();
    setCsrfToken("");
    vi.clearAllMocks();
    globalThis.IS_REACT_ACT_ENVIRONMENT = undefined;
  });

  it("does not navigate when owner A logout resolves after owner B mounts", async () => {
    const logout = deferred<string>();
    vi.mocked(logoutCurrentSession).mockReturnValue(logout.promise);
    await act(async () => root.render(<Harness accountId={1} />));
    act(() => findLogoutButton(container).click());
    const signal = vi.mocked(logoutCurrentSession).mock.calls[0]?.[0];
    expect(signal?.aborted).toBe(false);

    setCsrfToken("csrf-b", 2);
    await act(async () => root.render(<Harness accountId={2} />));
    expect(signal?.aborted).toBe(true);
    await act(async () => logout.resolve("/login"));

    expect(navigateBrowser).not.toHaveBeenCalled();
    expect(container.textContent).toContain("owner-2");
  });

  it("does not navigate when logout resolves after unmount", async () => {
    const logout = deferred<string>();
    vi.mocked(logoutCurrentSession).mockReturnValue(logout.promise);
    await act(async () => root.render(<Harness accountId={1} />));
    act(() => findLogoutButton(container).click());
    const signal = vi.mocked(logoutCurrentSession).mock.calls[0]?.[0];
    act(() => root.unmount());
    expect(signal?.aborted).toBe(true);
    await act(async () => logout.resolve("/login"));

    expect(navigateBrowser).not.toHaveBeenCalled();
  });
});

function findLogoutButton(container: HTMLElement) {
  const button = [...container.querySelectorAll("button")]
    .find((candidate) => candidate.textContent?.includes("Esci"));
  if (!(button instanceof HTMLButtonElement)) throw new Error("Logout button non trovato");
  return button;
}
