import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";

import { AccountsWorkspace } from "@/features/account-management/components/accounts-workspace";
import {
  useAccountManagement,
  useApiTokenAudit,
} from "@/features/account-management/use-account-management";

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
});
