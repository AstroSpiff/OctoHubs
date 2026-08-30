import type { CollectionEditorState } from "@/features/collections/collection-editor-state";
import { boundedWholeNumberInput } from "@/lib/numeric-input";

type CollectionEditorAutomationFieldsProps = {
  form: CollectionEditorState;
  disabled: boolean;
  onUpdate: (changes: Partial<CollectionEditorState>) => void;
};

function CollectionEditorAutomationFields({
  form,
  disabled,
  onUpdate,
}: CollectionEditorAutomationFieldsProps) {
  return (
    <>
      <div className="collection-editor-fields">
        <label>
          <span>Visibilità dal</span>
          <input
            value={form.season_start}
            disabled={disabled}
            onChange={(event) => onUpdate({ season_start: event.target.value })}
            placeholder="MM-GG"
          />
        </label>
        <label>
          <span>Visibilità fino al</span>
          <input
            value={form.season_end}
            disabled={disabled}
            onChange={(event) => onUpdate({ season_end: event.target.value })}
            placeholder="MM-GG"
          />
        </label>
        <label>
          <span>Frequenza automazione (%)</span>
          <input
            type="number"
            min="0"
            max="100"
            value={form.auto_frequency}
            disabled={disabled}
            onChange={(event) =>
              onUpdate({
                auto_frequency: boundedWholeNumberInput(event.target.value, 0, 100),
              })
            }
          />
        </label>
      </div>
      <div className="collection-editor-switches">
        <CollectionToggle
          label="Abilita subito"
          checked={form.enabled}
          disabled={disabled}
          onChange={(enabled) => onUpdate({ enabled })}
        />
        <CollectionToggle
          label="Aggiorna metadata dopo sync"
          checked={form.refresh_metadata}
          disabled={disabled}
          onChange={(refresh_metadata) => onUpdate({ refresh_metadata })}
        />
        <CollectionToggle
          label="Usa descrizione della fonte"
          checked={form.use_source_description}
          disabled={disabled}
          onChange={(use_source_description) =>
            onUpdate({ use_source_description })
          }
        />
        <CollectionToggle
          label="Esegui automaticamente"
          checked={form.auto_enabled}
          disabled={disabled}
          onChange={(auto_enabled) => onUpdate({ auto_enabled })}
        />
      </div>
    </>
  );
}

function CollectionToggle({
  label,
  checked,
  disabled,
  onChange,
}: {
  label: string;
  checked: boolean;
  disabled: boolean;
  onChange: (value: boolean) => void;
}) {
  return (
    <label>
      <input
        type="checkbox"
        checked={checked}
        disabled={disabled}
        onChange={(event) => onChange(event.target.checked)}
      />
      {label}
    </label>
  );
}

export { CollectionEditorAutomationFields };
