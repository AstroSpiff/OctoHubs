import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { SettingsScopePanel } from "@/features/user-settings/components/settings-scope-panel";
import { normalizeUserSettings } from "@/features/user-settings/settings-model";

describe("SettingsScopePanel", () => {
  it("keeps per-library landing controls in the single-user editor", () => {
    const markup = renderToStaticMarkup(
      <SettingsScopePanel
        scope="display_preferences"
        categories={[{
          id: "home",
          label: "Pagina Home",
          display_preferences: [{
            key: "__library_landing__",
            label: "Schermata predefinita per libreria",
            type: "library_landing",
            group: "Schermate predefinite",
          }],
        }]}
        settings={normalizeUserSettings({
          display_preferences: { "landing-movies": "suggestions" },
        })}
        libraryItems={[{
          id: "movies",
          name: "Film",
          collection_type: "movies",
          group_key: "movies:main",
        }]}
        disabled={false}
        onChange={() => undefined}
      />,
    );

    expect(markup).toContain("Schermata predefinita per libreria");
    expect(markup).toContain("Schermate predefinite");
    expect(markup).toContain("Film (movies)");
    expect(markup).toContain('value="suggestions" selected=""');
  });

  it("renders installed Emby features as accessible feature toggles", () => {
    const markup = renderToStaticMarkup(
      <SettingsScopePanel
        scope="policy"
        categories={[{
          id: "access",
          label: "Accesso e permessi",
          policy: [{
            key: "RestrictedFeatures",
            label: "Funzionalità limitate",
            type: "list",
            group: "Accesso alle funzionalità",
          }],
        }]}
        settings={normalizeUserSettings({
          policy: { RestrictedFeatures: ["feature-cinema"] },
        })}
        libraryItems={[]}
        featureItems={[{ id: "feature-cinema", name: "Cinema Mode" }]}
        disabled={false}
        onChange={() => undefined}
      />,
    );

    expect(markup).toContain("Funzionalità installate");
    expect(markup).toContain("Cinema Mode");
  });
});
