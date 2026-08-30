import type {
  SettingsCategory,
  SettingsFeatureItem,
  SettingsField,
} from "@/features/user-settings/types";

function featureAccessField(items: SettingsFeatureItem[]): SettingsField | null {
  if (!items.length) return null;
  return {
    key: "RestrictedFeatures",
    label: "Funzionalità installate",
    type: "feature_access",
    group: "Accesso alle funzionalità",
    options: items.map((item) => ({
      value: item.id,
      label: item.name || item.id,
      feature_type: item.feature_type,
    })),
    description:
      "Interruttore acceso = funzione consentita. Se lo spegni, OctoHubs salva il relativo ID nelle funzionalità limitate.",
  };
}

function prepareSettingsCategories(
  categories: SettingsCategory[],
  featureItems: SettingsFeatureItem[],
): SettingsCategory[] {
  const featureField = featureAccessField(featureItems);
  if (!featureField) return categories;

  return categories.map((category) => {
    if (category.id !== "access") return category;
    return {
      ...category,
      policy: (category.policy || []).map((field) =>
        field.key === "RestrictedFeatures" ? featureField : field,
      ),
    };
  });
}

export { prepareSettingsCategories };
