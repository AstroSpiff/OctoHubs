import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";

import { AccountsWorkspace } from "@/features/account-management/components/accounts-workspace";
import {
  useAccountManagement,
  useApiTokenAudit,
} from "@/features/account-management/use-account-management";
import { WorkspaceCapabilitiesProvider } from "@/features/session/workspace-capabilities";

vi.mock("@/features/account-management/use-account-management", () => ({
  useAccountManagement: vi.fn(),
  useApiTokenAudit: vi.fn(),
}));

describe("AccountsWorkspace", () => {
  it("propagates a profile query error with retry instead of loading forever", () => {
    vi.mocked(useAccountManagement).mockReturnValue({
      profile: {
        data: undefined,
        error: new Error("Profilo non disponibile"),
        isFetching: false,
        refetch: vi.fn(),
      },
      create: { error: null },
      update: { error: null },
      remove: { error: null },
      createToken: { error: null },
      revokeToken: { error: null },
      rotateToken: { error: null },
    } as unknown as ReturnType<typeof useAccountManagement>);
    vi.mocked(useApiTokenAudit).mockReturnValue(
      {} as ReturnType<typeof useApiTokenAudit>,
    );

    const markup = renderToStaticMarkup(<AccountsWorkspace />);

    expect(markup).toContain("Profilo non disponibile");
    expect(markup).toContain("Riprova");
    expect(markup).not.toContain("Caricamento account...");
  });

  it("does not render cached admin controls after write capability is revoked", () => {
    const query = (data: unknown) => ({
      data,
      error: null,
      isFetching: false,
      isLoading: false,
      refetch: vi.fn(),
    });
    vi.mocked(useAccountManagement).mockReturnValue({
      profile: query({
        id: 1,
        username: "owner",
        email: "",
        role: "admin",
        preferences: {
          primary_navigation: "sidebar",
          secondary_navigation: "sidebar",
          tab_order: [],
        },
      }),
      accounts: query([{ id: 2, username: "admin-control-canary", role: "viewer" }]),
      apiTokens: query(undefined),
      accountOperations: { pendingKeys: new Set(), errors: {}, clear: vi.fn() },
      create: { error: null, isPending: false, reset: vi.fn() },
      update: { error: null, reset: vi.fn() },
      remove: { error: null, reset: vi.fn() },
      updatePassword: { error: null, isPending: false },
      createToken: { error: null, isPending: false, reset: vi.fn() },
      revokeToken: { error: null, isPending: false, reset: vi.fn() },
      rotateToken: { error: null, isPending: false, reset: vi.fn() },
    } as unknown as ReturnType<typeof useAccountManagement>);
    vi.mocked(useApiTokenAudit).mockReturnValue(
      query(undefined) as unknown as ReturnType<typeof useApiTokenAudit>,
    );

    const markup = renderToStaticMarkup(
      <WorkspaceCapabilitiesProvider canMutate={false}>
        <AccountsWorkspace />
      </WorkspaceCapabilitiesProvider>,
    );

    expect(markup).not.toContain("admin-control-canary");
  });
});
