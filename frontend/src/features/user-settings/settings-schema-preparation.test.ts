import { describe, expect, it } from "vitest";

import { prepareSettingsCategories } from "@/features/user-settings/settings-schema-preparation";

describe("settings schema preparation", () => {
  it("replaces raw restricted feature IDs with the installed-feature controls", () => {
    const categories = [{
      id: "access",
      policy: [{ key: "RestrictedFeatures", label: "Funzionalità limitate", type: "list" }],
    }];

    expect(prepareSettingsCategories(categories, [{ id: "feature-a", name: "Cinema Mode", feature_type: "Premium" }])).toEqual([{
      id: "access",
      policy: [{
        key: "RestrictedFeatures",
        label: "Funzionalità installate",
        type: "feature_access",
        group: "Accesso alle funzionalità",
        options: [{ value: "feature-a", label: "Cinema Mode", feature_type: "Premium" }],
        description: "Interruttore acceso = funzione consentita. Se lo spegni, OctoHubs salva il relativo ID nelle funzionalità limitate.",
      }],
    }]);
    expect(categories[0].policy?.[0].type).toBe("list");
  });
});
