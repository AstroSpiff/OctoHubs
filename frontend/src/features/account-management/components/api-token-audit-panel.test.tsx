import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { ApiTokenAuditPanel } from "@/features/account-management/components/api-token-audit-panel";

describe("ApiTokenAuditPanel", () => {
  it("shows safe audit metadata without rendering a token secret", () => {
    const markup = renderToStaticMarkup(
      <ApiTokenAuditPanel
        events={[{
          id: 4,
          at: "2026-08-24T13:00:00+00:00",
          token_id: 2,
          token_name: "External AI",
          token_prefix: "ohs_visible",
          action: "api_token_denied",
          result: "denied",
          required_scope: "write:configuration",
          method: "POST",
          path: "/api/telegram/action",
          api_version: "legacy",
          ip_address: "203.0.113.10",
          user_agent: "external-ai-test",
        }]}
        filters={{ result: "denied" }}
        loading={false}
        tokens={[]}
        onChangeFilters={() => undefined}
        onExport={async () => new Blob()}
        onRefresh={() => undefined}
      />,
    );

    expect(markup).toContain("Audit token");
    expect(markup).toContain("External AI");
    expect(markup).toContain("Rifiutato");
    expect(markup).toContain("POST /api/telegram/action");
    expect(markup).toContain("Legacy");
    expect(markup).not.toContain("ohs_secret_value");
  });
});
