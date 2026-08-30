import type { SettingsField } from "@/features/user-settings/types";

type SettingsFeatureAccessFieldProps = {
  field: SettingsField;
  value: unknown;
  disabled: boolean;
  onChange: (value: string[]) => void;
};

function SettingsFeatureAccessField({
  field,
  value,
  disabled,
  onChange,
}: SettingsFeatureAccessFieldProps) {
  const restrictedIds = new Set(Array.isArray(value) ? value.map(String) : []);
  const options = field.options || [];
  const knownIds = new Set(options.map((option) => String(option.value)));
  const unresolvedIds = [...restrictedIds].filter((id) => !knownIds.has(id));

  function setAccess(id: string, allowed: boolean) {
    const next = new Set(restrictedIds);
    if (allowed) next.delete(id);
    else next.add(id);
    onChange([...next]);
  }

  return (
    <section className="user-settings-field user-settings-feature-access">
      <header>
        <strong>{field.label || field.key}</strong>
        {field.description ? <small>{field.description}</small> : null}
      </header>
      {options.length || unresolvedIds.length ? (
        <div className="user-settings-feature-list">
          {options.map((option) => {
            const id = String(option.value);
            return (
              <label key={id} className="user-settings-feature-item">
                <span>
                  <strong title={id}>{option.label}</strong>
                  {option.feature_type ? <small>{option.feature_type}</small> : null}
                </span>
                <input
                  type="checkbox"
                  checked={!restrictedIds.has(id)}
                  disabled={disabled}
                  aria-label={`Consenti ${option.label}`}
                  onChange={(event) => setAccess(id, event.target.checked)}
                />
              </label>
            );
          })}
          {unresolvedIds.map((id) => (
            <label key={id} className="user-settings-feature-item is-unresolved">
              <span>
                <strong title={id}>ID non risolto: {id}</strong>
                <small>Non disponibile su questo server</small>
              </span>
              <input
                type="checkbox"
                checked={false}
                disabled={disabled}
                aria-label={`Consenti la funzionalita non risolta ${id}`}
                onChange={(event) => setAccess(id, event.target.checked)}
              />
            </label>
          ))}
        </div>
      ) : (
        <p className="user-settings-feature-empty">
          Nessuna funzionalità dinamica disponibile da Emby.
        </p>
      )}
    </section>
  );
}

export { SettingsFeatureAccessField };
