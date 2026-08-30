import {
  libraryItemIsSelected,
  toggleLibraryItem,
  unresolvedLibraryIds,
} from "@/features/user-settings/library-multi-selection";
import type {
  LibrarySettingItem,
  SettingsField,
} from "@/features/user-settings/types";

type SettingsLibraryMultiFieldProps = {
  field: SettingsField;
  value: unknown;
  items: LibrarySettingItem[];
  disabled: boolean;
  onChange: (value: string[]) => void;
};

function SettingsLibraryMultiField({
  field,
  value,
  items,
  disabled,
  onChange,
}: SettingsLibraryMultiFieldProps) {
  const selectedIds = new Set(Array.isArray(value) ? value.map(String) : []);
  const unresolvedIds = unresolvedLibraryIds(value, items);
  const label = field.label || field.key;

  return (
    <section className="user-settings-field user-settings-library-multi">
      <header>
        <strong>{label}</strong>
        {field.description ? <small>{field.description}</small> : null}
      </header>
      {items.length || unresolvedIds.length ? (
        <div className="user-settings-library-multi-list">
          {items.map((item) => {
            const itemLabel = `${item.name || item.id} (${item.collection_type || "Libreria"})`;
            return (
              <label key={item.id} className="user-settings-library-multi-item">
                <span>
                  <strong title={itemLabel}>{itemLabel}</strong>
                  {item.group_key ? (
                    <small title="Questa libreria appartiene a un gruppo sincronizzabile.">
                      Gruppo
                    </small>
                  ) : null}
                </span>
                <input
                  type="checkbox"
                  checked={libraryItemIsSelected(item, selectedIds)}
                  disabled={disabled}
                  onChange={(event) =>
                    onChange(toggleLibraryItem(value, item, event.target.checked))
                  }
                />
              </label>
            );
          })}
          {unresolvedIds.map((id) => (
            <label key={id} className="user-settings-library-multi-item is-unresolved">
              <span>
                <strong title={id}>ID: {id}</strong>
                <small>Non disponibile su questo server</small>
              </span>
              <input
                type="checkbox"
                checked
                disabled={disabled}
                onChange={(event) => {
                  if (!event.target.checked) {
                    onChange((Array.isArray(value) ? value : []).map(String).filter((item) => item !== id));
                  }
                }}
              />
            </label>
          ))}
        </div>
      ) : (
        <p className="user-settings-library-multi-empty">
          Nessuna libreria disponibile per questo server.
        </p>
      )}
      <small className="user-settings-library-multi-hint">
        Le librerie con badge Gruppo si sincronizzano tra server. Le altre restano locali.
      </small>
    </section>
  );
}

export { SettingsLibraryMultiField };
