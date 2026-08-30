import { Plus, Trash2 } from "@/components/ui/icons";

import { Button } from "@/components/ui/button";
import { boundedWholeNumberInput } from "@/lib/numeric-input";
import {
  normalizeScheduleEntries,
  type ScheduleEntry,
} from "@/features/user-settings/schedule-state";
import type { SettingsField } from "@/features/user-settings/types";

type SettingsScheduleFieldProps = {
  field: SettingsField;
  value: unknown;
  disabled: boolean;
  onChange: (value: ScheduleEntry[]) => void;
};

function SettingsScheduleField({
  field,
  value,
  disabled,
  onChange,
}: SettingsScheduleFieldProps) {
  const defaultDay = String(field.options?.[0]?.value || "");
  const entries = normalizeScheduleEntries(value, defaultDay);

  function update(index: number, patch: Partial<ScheduleEntry>) {
    onChange(entries.map((entry, entryIndex) => entryIndex === index ? { ...entry, ...patch } : entry));
  }

  return (
    <section className="user-settings-field user-settings-schedule">
      <header>
        <strong>{field.label || field.key}</strong>
        {field.description ? <small>{field.description}</small> : null}
      </header>
      {entries.length ? (
        <div className="user-settings-schedule-list">
          {entries.map((entry, index) => (
            <div key={`${entry.DayOfWeek}:${index}`} className="user-settings-schedule-row">
              <select aria-label={`Giorno fascia ${index + 1}`} value={entry.DayOfWeek} disabled={disabled} onChange={(event) => update(index, { DayOfWeek: event.target.value })}>
                {field.options?.map((option) => <option key={String(option.value)} value={String(option.value)}>{option.label}</option>)}
              </select>
              <input aria-label={`Ora inizio fascia ${index + 1}`} type="number" min="0" max="23" step="1" value={entry.StartHour} disabled={disabled} onChange={(event) => update(index, { StartHour: boundedWholeNumberInput(event.target.value, 0, 23) })} />
              <input aria-label={`Ora fine fascia ${index + 1}`} type="number" min="0" max="23" step="1" value={entry.EndHour} disabled={disabled} onChange={(event) => update(index, { EndHour: boundedWholeNumberInput(event.target.value, 0, 23) })} />
              <Button type="button" variant="ghost" size="icon" title="Rimuovi fascia" aria-label={`Rimuovi fascia ${index + 1}`} disabled={disabled} onClick={() => onChange(entries.filter((_, entryIndex) => entryIndex !== index))}>
                <Trash2 size={15} aria-hidden="true" />
              </Button>
            </div>
          ))}
        </div>
      ) : (
        <p className="user-settings-schedule-empty">Nessuna fascia oraria configurata.</p>
      )}
      <Button type="button" variant="secondary" size="compact" disabled={disabled || !defaultDay} onClick={() => onChange([...entries, { DayOfWeek: defaultDay, StartHour: 0, EndHour: 23 }])}>
        <Plus size={15} aria-hidden="true" />
        Aggiungi fascia
      </Button>
    </section>
  );
}

export { SettingsScheduleField };
