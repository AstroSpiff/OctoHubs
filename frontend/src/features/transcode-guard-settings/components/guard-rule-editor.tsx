import { PencilLine } from "@/components/ui/icons";

import { Card } from "@/components/ui/card";
import { RuleActionFields } from "@/features/transcode-guard-settings/components/rule-action-fields";
import { RuleExclusions } from "@/features/transcode-guard-settings/components/rule-exclusions";
import { RuleMatchingFields } from "@/features/transcode-guard-settings/components/rule-matching-fields";
import { RuleMessageFields } from "@/features/transcode-guard-settings/components/rule-message-fields";
import { RuleTargets } from "@/features/transcode-guard-settings/components/rule-targets";
import type { GuardRule, GuardServerOption } from "@/features/transcode-guard-settings/types";

function GuardRuleEditor({ rule, index, servers, onChange }: { rule?: GuardRule; index: number; servers: GuardServerOption[]; onChange: (changes: Partial<GuardRule>) => void }) {
  if (!rule) return <Card className="guard-rule-editor-empty">Seleziona una regola per modificarla.</Card>;
  return (
    <Card className="guard-rule-editor">
      <header><div><h4 className="contextual-heading" title="Dettaglio regola"><PencilLine size={18} aria-hidden="true" /> Posizione {index + 1}</h4></div><label className="guard-settings-switch"><input type="checkbox" checked={rule.enabled} onChange={(event) => onChange({ enabled: event.target.checked })} /><span>Attiva</span></label></header>
      <div className="rule-editor-content">
        <label className="guard-setting-field"><span>Nome</span><input value={rule.name} placeholder="Blocco transcode 4K" onChange={(event) => onChange({ name: event.target.value })} /></label>
        <RuleTargets rule={rule} servers={servers} onChange={onChange} />
        <RuleMatchingFields rule={rule} onChange={onChange} />
        <RuleActionFields rule={rule} onChange={onChange} />
        <RuleMessageFields rule={rule} onChange={onChange} />
        <RuleExclusions rule={rule} onChange={onChange} />
      </div>
    </Card>
  );
}

export { GuardRuleEditor };
