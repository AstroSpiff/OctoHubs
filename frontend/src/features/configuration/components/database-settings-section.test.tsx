import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { DatabaseSettingsSection } from "@/features/configuration/components/database-settings-section";

describe("DatabaseSettingsSection", () => {
  it("keeps the deploy environment precedence visible beside the database form", () => {
    const markup = renderToStaticMarkup(
      <DatabaseSettingsSection
        value={{ host: "postgres", port: "5432", name: "octohubs", user: "octohubs", driver: "postgresql+psycopg2", params: "" }}
        snapshot={{ enabled: true, host: "postgres", port: "5432", name: "octohubs", user: "octohubs", driver: "postgresql+psycopg2", url_configured: true, params: "", password_configured: true }}
        onChange={() => undefined}
      />,
    );

    expect(markup).toContain('class="database-settings-help"');
    expect(markup).toContain('class="configuration-state configuration-state--ok"');
    expect(markup).toContain("OCTOHUBS_DB_URL");
    expect(markup).toContain("OCTOHUBS_DB_PASSWORD_FILE");
    expect(markup).toContain("URL di connessione");
    expect(markup).toContain("Rimuovi URL di connessione salvato");
  });
});
