import { Ban } from "@/components/ui/icons";

import { listFromInput } from "@/features/transcode-guard-settings/rule-model";
import type { GuardRule } from "@/features/transcode-guard-settings/types";

const fields: Array<{ key: "excluded_users" | "excluded_clients" | "excluded_devices" | "excluded_ips"; label: string; placeholder: string }> = [
  { key: "excluded_users", label: "Utenti esclusi", placeholder: "Luca, Margo" },
  { key: "excluded_clients", label: "Client esclusi", placeholder: "Emby for Android" },
  { key: "excluded_devices", label: "Dispositivi esclusi", placeholder: "Shield, iPad" },
  { key: "excluded_ips", label: "IP o reti escluse", placeholder: "192.168.1.10, 10.0.0.0/24" },
];

function RuleExclusions({ rule, onChange }: { rule: GuardRule; onChange: (changes: Partial<GuardRule>) => void }) {
  return (
    <details className="rule-editor-details">
      <summary><Ban size={17} aria-hidden="true" /> Esclusioni della regola</summary>
      <div className="rule-editor-details-content rule-editor-grid rule-editor-grid--two">
        {fields.map((field) => <label key={field.key} className="guard-setting-field"><span>{field.label}</span><input value={rule[field.key].join(", ")} placeholder={field.placeholder} onChange={(event) => onChange({ [field.key]: listFromInput(event.target.value) })} /></label>)}
      </div>
    </details>
  );
}

export { RuleExclusions };
