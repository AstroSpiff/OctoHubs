import { ListChecks, Plus } from "@/components/ui/icons";

import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { GuardRuleRow } from "@/features/transcode-guard-settings/components/guard-rule-row";
import type { GuardRule } from "@/features/transcode-guard-settings/types";

function GuardRuleList({ rules, selectedId, onSelect, onAdd, onMove, onToggle, onDuplicate, onDelete }: {
  rules: GuardRule[]; selectedId: string; onSelect: (id: string) => void; onAdd: () => void; onMove: (id: string, direction: number) => void;
  onToggle: (id: string) => void; onDuplicate: (id: string) => void; onDelete: (id: string) => void;
}) {
  return (
    <Card className="guard-rules-list-card">
      <header><div><h4 className="contextual-heading" title="Ordine di valutazione"><ListChecks size={18} aria-hidden="true" /> Regole stream</h4></div><Button type="button" requiresWriteAccess size="compact" variant="secondary" onClick={onAdd}><Plus size={15} aria-hidden="true" /> Regola</Button></header>
      <p className="guard-rules-list-help">La prima regola valida decide l'intervento.</p>
      <div className="guard-rules-list">
        {rules.map((rule, index) => <GuardRuleRow key={rule.id} rule={rule} selected={rule.id === selectedId} index={index} total={rules.length} onSelect={() => onSelect(rule.id)} onMove={(direction) => onMove(rule.id, direction)} onToggle={() => onToggle(rule.id)} onDuplicate={() => onDuplicate(rule.id)} onDelete={() => onDelete(rule.id)} />)}
      </div>
    </Card>
  );
}

export { GuardRuleList };
