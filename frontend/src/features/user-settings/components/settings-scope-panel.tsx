import { SettingsLibraryAccess } from "@/features/user-settings/components/settings-library-access";
import { SettingsFieldControl } from "@/features/user-settings/components/settings-field";
import { SettingsLibraryLandingField } from "@/features/user-settings/components/settings-library-landing-field";
import { groupSettingsFields } from "@/features/user-settings/settings-field-groups";
import { prepareSettingsCategories } from "@/features/user-settings/settings-schema-preparation";
import { updateSettingsValue } from "@/features/user-settings/settings-model";
import type {
  SettingsCategory,
  SettingsFeatureItem,
  SettingsScope,
  UserSettings,
} from "@/features/user-settings/types";

type SettingsScopePanelProps = {
  scope: SettingsScope;
  categories: SettingsCategory[];
  settings: UserSettings;
  libraryItems: Parameters<typeof SettingsLibraryAccess>[0]["items"];
  featureItems?: SettingsFeatureItem[];
  disabled: boolean;
  onChange: (settings: UserSettings) => void;
};

function SettingsScopePanel({
  scope,
  categories,
  settings,
  libraryItems,
  featureItems = [],
  disabled,
  onChange,
}: SettingsScopePanelProps) {
  const sections = prepareSettingsCategories(categories, featureItems)
    .map((category) => ({
      category,
      fields: (category[scope] || []).filter((field) => !field.hidden),
    }))
    .filter(
      ({ category, fields }) =>
        fields.length || (scope === "policy" && category.libraries),
    );

  if (!sections.length) {
    return (
      <p className="user-settings-empty">
        Nessuna impostazione disponibile in questa sezione.
      </p>
    );
  }

  return (
    <div className="user-settings-sections">
      {sections.map(({ category, fields }, index) => (
        <details key={category.id} className="user-settings-section" open={index === 0}>
          <summary>
            <span>{category.label || category.id}</span>
            <small>{fields.length ? `${fields.length} campi` : "Librerie"}</small>
          </summary>
          <div>
            {category.description ? <p>{category.description}</p> : null}
            {scope === "policy" && category.libraries ? (
              <SettingsLibraryAccess
                settings={settings}
                items={libraryItems}
                disabled={disabled}
                onChange={(libraries) => onChange({ ...settings, libraries })}
              />
            ) : null}
            {groupSettingsFields(fields).map((fieldGroup, groupIndex) => (
              <section key={`${fieldGroup.label || "fields"}:${groupIndex}`} className="user-settings-field-group">
                {fieldGroup.label ? <h4>{fieldGroup.label}</h4> : null}
                {fieldGroup.fields.map((field) => {
                  if (field.type === "library_landing") {
                    return (
                      <SettingsLibraryLandingField
                        key={`${scope}:${field.key}`}
                        field={field}
                        preferences={settings.display_preferences}
                        items={libraryItems}
                        disabled={disabled}
                        onChange={(key, value) =>
                          onChange(
                            updateSettingsValue(
                              settings,
                              "display_preferences",
                              key,
                              value,
                            ),
                          )
                        }
                      />
                    );
                  }

                  return (
                    <SettingsFieldControl
                      key={`${scope}:${field.key}`}
                      field={field}
                      scope={scope}
                      value={settings[scope][field.key]}
                      disabled={disabled}
                      libraryItems={libraryItems}
                      onChange={(value) =>
                        onChange(updateSettingsValue(settings, scope, field.key, value))
                      }
                    />
                  );
                })}
              </section>
            ))}
          </div>
        </details>
      ))}
    </div>
  );
}

export { SettingsScopePanel };
