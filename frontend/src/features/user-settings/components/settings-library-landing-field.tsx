import {
  libraryLandingKey,
  libraryLandingOptions,
} from "@/features/user-settings/library-landing";
import type {
  LibrarySettingItem,
  SettingsField,
} from "@/features/user-settings/types";

function SettingsLibraryLandingField({
  field,
  preferences,
  items,
  disabled,
  onChange,
}: {
  field: SettingsField;
  preferences: Record<string, unknown>;
  items: LibrarySettingItem[];
  disabled: boolean;
  onChange: (key: string, value: string) => void;
}) {
  return (
    <section className="user-settings-field user-settings-library-landing">
      <header>
        <strong>{field.label || field.key}</strong>
        {field.description ? <small>{field.description}</small> : null}
      </header>
      {items.length ? (
        <div className="user-settings-library-landing-list">
          {items.map((item) => {
            const key = libraryLandingKey(item);
            const currentValue = String(preferences[key] ?? "");
            const options = libraryLandingOptions(item.collection_type);
            const knownValues = new Set(options.map((option) => option.value));
            const label = `${item.name || item.id} (${item.collection_type || "Libreria"})`;
            return (
              <label key={item.id} className="user-settings-library-landing-row">
                <span>
                  <strong title={label}>{label}</strong>
                  {item.group_key ? <small title="Questa libreria appartiene a un gruppo sincronizzabile.">Gruppo</small> : null}
                </span>
                <select value={currentValue} disabled={disabled} onChange={(event) => onChange(key, event.target.value)}>
                  {!knownValues.has(currentValue) ? <option value={currentValue}>Valore attuale: {currentValue}</option> : null}
                  {options.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}
                </select>
              </label>
            );
          })}
        </div>
      ) : (
        <p className="user-settings-library-landing-empty">Nessuna libreria disponibile per questo server.</p>
      )}
    </section>
  );
}

export { SettingsLibraryLandingField };
