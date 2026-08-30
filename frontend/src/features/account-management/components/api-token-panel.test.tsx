import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { ApiTokenPanel } from "@/features/account-management/components/api-token-panel";

describe("ApiTokenPanel", () => {
  it("shows existing token metadata without exposing a secret", () => {
    const markup = renderToStaticMarkup(
      <ApiTokenPanel
        availablePermissionProfiles={[
          { id: "read_only", scopes: ["read:status"] },
          { id: "operator", scopes: ["read:status", "write:event_bridge"] },
          { id: "administrator", scopes: ["admin:all"] },
        ]}
        tokens={[
          {
            id: 1,
            name: "External AI",
            prefix: "ohs_visible",
            scopes: ["read:status", "write:event_bridge"],
            permission_profile: "operator",
            is_active: true,
            is_expired: false,
            status: "active",
            created_at: "2026-08-21T10:00:00+00:00",
            last_used_at: null,
            revoked_at: null,
            expires_at: "2026-11-19T10:00:00+00:00",
            last_action: {
              action: "api_token_read",
              at: "2026-08-21T10:04:00+00:00",
              method: "GET",
              path: "/api/system/status",
              required_scope: "read:status",
              result: "allowed",
            },
          },
        ]}
        loading={false}
        creating={false}
        onCreate={async () => {
          throw new Error("not called");
        }}
        onRevoke={async () => undefined}
        onRotate={async () => { throw new Error("not called"); }}
      />,
    );

    expect(markup).toContain("API token");
    expect(markup).toContain("External AI");
    expect(markup).toContain("ohs_visible...");
    expect(markup).toContain("Modifica Event Bridge");
    expect(markup).toContain("Sola lettura");
    expect(markup).toContain("Operatore");
    expect(markup).toContain("Amministratore");
    expect(markup).toContain("Lettura: GET /api/system/status");
    expect(markup).not.toContain("ohs_secret_value");
  });
});
