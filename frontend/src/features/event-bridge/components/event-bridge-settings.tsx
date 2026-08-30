import { RefreshCw, Save } from "@/components/ui/icons";

import { Button } from "@/components/ui/button";
import type { EventBridgeSettings } from "@/features/event-bridge/types";
import {
  booleanFields,
  eventFields,
  numericFields,
} from "@/features/event-bridge/settings-catalog";
import { boundedWholeNumberInput } from "@/lib/numeric-input";

function updateSetting<K extends keyof EventBridgeSettings>(
  settings: EventBridgeSettings,
  key: K,
  value: EventBridgeSettings[K],
): EventBridgeSettings {
  return { ...settings, [key]: value };
}

function EventBridgeSettingsForm({
  settings,
  dirty,
  saving,
  locked,
  onChange,
  onSave,
}: {
  settings: EventBridgeSettings;
  dirty: boolean;
  saving: boolean;
  locked: boolean;
  onChange: (settings: EventBridgeSettings) => void;
  onSave: () => void;
}) {
  return (
    <div className="bridge-settings-content">
      <div className="switch-grid">
        {booleanFields.map((field) => (
          <label className="switch-field" key={field.key}>
            <input
              type="checkbox"
              checked={Boolean(settings[field.key])}
              disabled={locked}
              onChange={(event) => onChange(updateSetting(settings, field.key, event.target.checked as never))}
            />
            <span>
              <strong>{field.label}</strong>
              <small>{field.description}</small>
            </span>
          </label>
        ))}
      </div>
      <div className="number-grid">
        {numericFields.map((field) => (
          <label className="field-label" key={field.key}>
            <span>{field.label}</span>
            <input
              type="number"
              min={field.minimum}
              value={Number(settings[field.key])}
              disabled={locked}
              onChange={(event) => onChange(updateSetting(
                settings,
                field.key,
                boundedWholeNumberInput(event.target.value, field.minimum) as never,
              ))}
            />
          </label>
        ))}
      </div>
      <div className="event-grid">
        {eventFields.map((field) => (
          <label className="field-label" key={field.key}>
            <span>{field.label}</span>
            <textarea
              rows={4}
              value={(settings[field.key] as string[]).join("\n")}
              disabled={locked}
              onChange={(event) => onChange(updateSetting(
                settings,
                field.key,
                event.target.value.split("\n").map((name) => name.trim()).filter(Boolean) as never,
              ))}
            />
          </label>
        ))}
      </div>
      <div className="bridge-save-row">
        <p>{dirty ? "Modifiche non applicate al plugin." : "Impostazioni allineate all'ultimo valore salvato in OctoHubs."}</p>
        <Button type="button" variant="primary" onClick={onSave} disabled={!dirty || locked}>
          {saving ? <RefreshCw className="animate-spin" size={16} aria-hidden="true" /> : <Save size={16} aria-hidden="true" />}
          {saving ? "Salvataggio..." : locked ? "Salvataggio in corso..." : "Salva e applica"}
        </Button>
      </div>
    </div>
  );
}

export { EventBridgeSettingsForm };
