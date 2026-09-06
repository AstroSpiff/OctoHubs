import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";

import { AccountProfilePanel } from "@/features/account-management/components/account-profile-panel";
import { ApiTokenPanel } from "@/features/account-management/components/api-token-panel";
import type { CurrentOctoHubsAccount } from "@/features/account-management/types";
import { WorkspaceCapabilitiesProvider } from "@/features/session/workspace-capabilities";

const account: CurrentOctoHubsAccount = {
  id: 7,
  username: "viewer",
  email: "viewer@example.test",
  role: "viewer",
  is_active: true,
  created_at: null,
  last_login: null,
  preferences: {
    primary_navigation: "sidebar",
    secondary_navigation: "tabs",
  },
};

function renderAccountPanels(canMutate: boolean) {
  return renderToStaticMarkup(
    <WorkspaceCapabilitiesProvider canMutate={canMutate}>
      <AccountProfilePanel
        account={account}
        saving={false}
        onChangePassword={vi.fn()}
      />
      <ApiTokenPanel
        availablePermissionProfiles={[{ id: "read_only", scopes: ["read:status"] }]}
        tokens={[{
          id: 1,
          name: "Token esistente",
          prefix: "ohs_test",
          scopes: ["read:status"],
          permission_profile: "read_only",
          is_active: true,
          is_expired: false,
          status: "active",
          created_at: null,
          last_used_at: null,
          revoked_at: null,
          expires_at: null,
          last_action: null,
        }]}
        loading={false}
        creating={false}
        onCreate={vi.fn()}
        onRevoke={vi.fn()}
        onRotate={vi.fn()}
      />
    </WorkspaceCapabilitiesProvider>,
  );
}

describe("account mutation capabilities", () => {
  it("keeps account data visible but hides every mutation from viewers", () => {
    const markup = renderAccountPanels(false);

    expect(markup).toContain("viewer@example.test");
    expect(markup).toContain("Token esistente");
    expect(markup).not.toContain("Modifica password");
    expect(markup).not.toContain("Nome token");
    expect(markup).not.toContain("Ruota Token esistente");
    expect(markup).not.toContain("Revoca Token esistente");
  });

  it("shows account mutations to users with write capability", () => {
    const markup = renderAccountPanels(true);

    expect(markup).toContain("Modifica password");
    expect(markup).toContain("Nome token");
    expect(markup).toContain("Ruota Token esistente");
    expect(markup).toContain("Revoca Token esistente");
  });
});
