import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { DatabaseSettingsSection } from "@/features/configuration/components/database-settings-section";

describe("DatabaseSettingsSection", () => {
  it("shows deployment-owned database settings without editable credentials", () => {
    const markup = renderToStaticMarkup(
      <DatabaseSettingsSection
        snapshot={{ enabled: true, host: "postgres", port: "5432", name: "octohubs", user: "octohubs", driver: "postgresql+psycopg2", url_configured: true, params: "", password_configured: true }}
      />,
    );

    expect(markup).toContain('class="database-settings-help"');
    expect(markup).toContain('class="configuration-state configuration-state--ok"');
    expect(markup).toContain("OCTOHUBS_DB_URL");
    expect(markup).toContain("OCTOHUBS_DB_PASSWORD_FILE");
    expect(markup).toContain("Gestito dal deployment");
    expect(markup).not.toContain("<input");
  });
});
