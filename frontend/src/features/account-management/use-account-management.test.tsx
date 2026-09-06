// @vitest-environment jsdom

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import * as accountApi from "@/features/account-management/api";
import type { OctoHubsAccount } from "@/features/account-management/types";
import { useAccountManagement } from "@/features/account-management/use-account-management";

vi.mock("@/features/account-management/api", () => ({
  createAccount: vi.fn(),
  createApiToken: vi.fn(),
  deleteAccount: vi.fn(),
  exportApiTokenAudit: vi.fn(),
  getAccounts: vi.fn().mockResolvedValue([]),
  getApiTokenAudit: vi.fn(),
  getApiTokens: vi.fn().mockResolvedValue({ tokens: [], available_permission_profiles: [] }),
  getCurrentAccount: vi.fn().mockResolvedValue({ id: 1, role: "admin" }),
  revokeApiToken: vi.fn(),
  rotateApiToken: vi.fn(),
  updateAccount: vi.fn(),
  updateCurrentPassword: vi.fn(),
}));

declare global {
  var IS_REACT_ACT_ENVIRONMENT: boolean | undefined;
}

let latest: ReturnType<typeof useAccountManagement> | undefined;

function Harness() {
  latest = useAccountManagement();
  return null;
}

describe("useAccountManagement account operations", () => {
  let container: HTMLDivElement;
  let root: ReturnType<typeof createRoot>;

  beforeEach(() => {
    globalThis.IS_REACT_ACT_ENVIRONMENT = true;
    latest = undefined;
    container = document.createElement("div");
    document.body.append(container);
    root = createRoot(container);
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    act(() => root.render(
      <QueryClientProvider client={client}>
        <Harness />
      </QueryClientProvider>,
    ));
  });

  afterEach(() => {
    act(() => root.unmount());
    container.remove();
    vi.clearAllMocks();
    globalThis.IS_REACT_ACT_ENVIRONMENT = undefined;
  });

  it("keeps concurrent account failures and pending state keyed by account", async () => {
    let rejectFirst!: (error: Error) => void;
    let resolveSecond!: (value: OctoHubsAccount) => void;
    const first = new Promise<OctoHubsAccount>((_, reject) => { rejectFirst = reject; });
    const second = new Promise<OctoHubsAccount>((resolve) => { resolveSecond = resolve; });
    vi.mocked(accountApi.updateAccount).mockImplementation((accountId) =>
      accountId === 1 ? first : second,
    );

    let firstRun!: Promise<unknown>;
    let secondRun!: Promise<unknown>;
    await act(async () => {
      firstRun = latest!.updateAccount(1, { is_active: false });
      secondRun = latest!.updateAccount(2, { is_active: false });
      await Promise.resolve();
    });
    expect(latest?.accountOperations.pendingKeys).toEqual(new Set(["1", "2"]));

    await act(async () => {
      rejectFirst(new Error("Account 1 non aggiornato"));
      await firstRun.catch(() => undefined);
    });
    expect(latest?.accountOperations.pendingKeys).toEqual(new Set(["2"]));
    expect(latest?.accountOperations.errors).toEqual({ "1": "Account 1 non aggiornato" });

    await act(async () => {
      resolveSecond({
        id: 2,
        username: "second",
        email: "",
        role: "user",
        is_active: false,
        created_at: null,
        last_login: null,
      });
      await secondRun;
    });
    expect(latest?.accountOperations.pendingKeys).toEqual(new Set());
    expect(latest?.accountOperations.errors).toEqual({ "1": "Account 1 non aggiornato" });
  });
});
