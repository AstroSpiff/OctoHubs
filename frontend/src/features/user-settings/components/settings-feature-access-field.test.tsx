import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { SettingsFeatureAccessField } from "@/features/user-settings/components/settings-feature-access-field";

describe("SettingsFeatureAccessField", () => {
  it("keeps unresolved restricted feature IDs visible alongside installed features", () => {
    const markup = renderToStaticMarkup(
      <SettingsFeatureAccessField
        field={{
          key: "RestrictedFeatures",
          label: "Funzionalità installate",
          type: "feature_access",
          options: [{ value: "cinema", label: "Cinema Mode", feature_type: "Premium" }],
        }}
        value={["removed-feature"]}
        disabled={false}
        onChange={() => undefined}
      />,
    );

    expect(markup).toContain("Cinema Mode");
    expect(markup).toContain("Premium");
    expect(markup).toContain("ID non risolto: removed-feature");
    expect(markup).toContain("Non disponibile su questo server");
  });
});
