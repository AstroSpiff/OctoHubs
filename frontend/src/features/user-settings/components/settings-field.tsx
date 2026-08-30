import { useEffect, useState } from "react";

import { SettingsLibraryMultiField } from "@/features/user-settings/components/settings-library-multi-field";
import { SettingsLibraryOrderField } from "@/features/user-settings/components/settings-library-order-field";
import { SettingsScheduleField } from "@/features/user-settings/components/settings-schedule-field";
import { SettingsFeatureAccessField } from "@/features/user-settings/components/settings-feature-access-field";
import { boundedWholeNumberInput } from "@/lib/numeric-input";
import type {
  LibrarySettingItem,
  SettingsField,
  SettingsScope,
} from "@/features/user-settings/types";

type SettingsFieldProps = {
  field: SettingsField;
  scope: SettingsScope;
  value: unknown;
  disabled: boolean;
  libraryItems?: LibrarySettingItem[];
  onChange: (value: unknown) => void;
};

function integerValue(field: SettingsField, value: string) {
  return boundedWholeNumberInput(
    value,
    typeof field.min === "number" ? field.min : Number.MIN_SAFE_INTEGER,
    typeof field.max === "number" ? field.max : Number.MAX_SAFE_INTEGER,
  );
}

function SettingsFieldControl({
  field,
  value,
  disabled,
  libraryItems = [],
  onChange,
}: SettingsFieldProps) {
  const type = field.type || "text";
  const label = field.label || field.key;

  if (type === "bool") return <label className="user-settings-toggle"><span><strong>{label}</strong>{field.description ? <small>{field.description}</small> : null}</span><input type="checkbox" checked={value === true} disabled={disabled} onChange={(event) => onChange(event.target.checked)} /></label>;

  if (type === "feature_access") {
    return <SettingsFeatureAccessField field={field} value={value} disabled={disabled} onChange={onChange} />;
  }

  if (type === "multiselect") {
    const selected = new Set(Array.isArray(value) ? value.map(String) : []);
    return <section className="user-settings-field"><header><strong>{label}</strong>{field.description ? <small>{field.description}</small> : null}</header><div className="user-settings-multiselect">{(field.options || []).map((option) => { const optionValue = String(option.value); const selectedOption = selected.has(optionValue); return <label key={optionValue}><input type="checkbox" checked={selectedOption} disabled={disabled} onChange={(event) => { const next = new Set(selected); if (event.target.checked) next.add(optionValue); else next.delete(optionValue); onChange([...next]); }} />{option.label}</label>; })}</div></section>;
  }

  if (type === "library_multi") {
    return <SettingsLibraryMultiField field={field} value={value} items={libraryItems} disabled={disabled} onChange={onChange} />;
  }

  if (type === "library_order") {
    return <SettingsLibraryOrderField field={field} value={value} items={libraryItems} disabled={disabled} onChange={onChange} />;
  }

  if (type === "schedule") {
    return <SettingsScheduleField field={field} value={value} disabled={disabled} onChange={onChange} />;
  }

  if (type === "list") {
    const text = Array.isArray(value) ? value.join("\n") : "";
    return <label className="user-settings-field"><span><strong>{label}</strong>{field.description ? <small>{field.description}</small> : null}</span><textarea rows={3} maxLength={field.max_length} placeholder={field.placeholder} value={text} disabled={disabled} onChange={(event) => onChange(event.target.value.split("\n").map((item) => item.trim()).filter(Boolean))} /><small>Un valore per riga.</small></label>;
  }

  if (type === "json") {
    return <StructuredField field={field} value={value} disabled={disabled} onChange={onChange} />;
  }

  if (type === "select" || type === "language" || (type === "int" && field.options?.length)) return <label className="user-settings-field"><span><strong>{label}</strong>{field.description ? <small>{field.description}</small> : null}</span><select value={String(value ?? "")} disabled={disabled} onChange={(event) => onChange(type === "int" ? integerValue(field, event.target.value) : event.target.value)}>{(field.options || []).map((option) => <option key={String(option.value)} value={String(option.value)}>{option.label}</option>)}</select></label>;

  return <label className="user-settings-field"><span><strong>{label}</strong>{field.description ? <small>{field.description}</small> : null}</span><input type={type === "int" ? "number" : type === "password" ? "password" : "text"} min={type === "int" ? field.min : undefined} max={type === "int" ? field.max : undefined} step={type === "int" ? "1" : undefined} inputMode={type === "int" ? "numeric" : undefined} maxLength={field.max_length} placeholder={field.placeholder} value={String(value ?? "")} disabled={disabled} onChange={(event) => onChange(type === "int" ? integerValue(field, event.target.value) : event.target.value)} /></label>;
}

function StructuredField({ field, value, disabled, onChange }: Omit<SettingsFieldProps, "scope">) {
  const label = field.label || field.key;
  const [text, setText] = useState(() => formatStructuredValue(value));
  const [error, setError] = useState("");

  useEffect(() => {
    setText(formatStructuredValue(value));
    setError("");
  }, [value]);

  function commit() {
    if (!text.trim()) {
      onChange([]);
      setError("");
      return;
    }
    try {
      onChange(JSON.parse(text));
      setError("");
    } catch {
      setError("Inserisci JSON valido prima di salvare.");
    }
  }

  return <label className="user-settings-field"><span><strong>{label}</strong>{field.description ? <small>{field.description}</small> : null}</span><textarea rows={5} value={text} disabled={disabled} onChange={(event) => setText(event.target.value)} onBlur={commit} /><small>Modifica il valore strutturato in JSON.</small>{error ? <small className="user-settings-field-error">{error}</small> : null}</label>;
}

function formatStructuredValue(value: unknown) {
  if (value === undefined || value === null || value === "") return "";
  return typeof value === "string" ? value : JSON.stringify(value, null, 2);
}

export { SettingsFieldControl };
