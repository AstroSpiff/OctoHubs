import { ArrowDown, ArrowUp, Copy, Power, Trash2 } from "@/components/ui/icons";

import { Button } from "@/components/ui/button";
import { modeLabels, ruleSummary } from "@/features/transcode-guard-settings/rule-model";
import type { GuardRule } from "@/features/transcode-guard-settings/types";
import { cn } from "@/lib/utils";

function GuardRuleRow({ rule, selected, index, total, onSelect, onMove, onToggle, onDuplicate, onDelete }: {
  rule: GuardRule; selected: boolean; index: number; total: number; onSelect: () => void; onMove: (direction: number) => void;
  onToggle: () => void; onDuplicate: () => void; onDelete: () => void;
}) {
  return (
    <article className={cn("guard-rule-row", selected && "is-selected", !rule.enabled && "is-disabled")}>
      <button type="button" className="guard-rule-select" onClick={onSelect} aria-pressed={selected}>
        <strong>{rule.name || "Regola senza nome"}</strong>
        <span>{ruleSummary(rule)}</span>
        <small>{modeLabels[rule.mode]} · {rule.server_ids.length ? `${rule.server_ids.length} server` : "nessun server"}</small>
      </button>
      <div className="guard-rule-actions">
        <Button size="icon" variant="ghost" type="button" requiresWriteAccess onClick={onToggle} title={rule.enabled ? "Disattiva regola" : "Attiva regola"} aria-label={rule.enabled ? "Disattiva regola" : "Attiva regola"}><Power size={15} aria-hidden="true" /></Button>
        <Button size="icon" variant="ghost" type="button" requiresWriteAccess onClick={() => onMove(-1)} disabled={index === 0} title="Sposta su" aria-label="Sposta su"><ArrowUp size={15} aria-hidden="true" /></Button>
        <Button size="icon" variant="ghost" type="button" requiresWriteAccess onClick={() => onMove(1)} disabled={index === total - 1} title="Sposta giù" aria-label="Sposta giù"><ArrowDown size={15} aria-hidden="true" /></Button>
        <Button size="icon" variant="ghost" type="button" requiresWriteAccess onClick={onDuplicate} title="Duplica regola" aria-label="Duplica regola"><Copy size={15} aria-hidden="true" /></Button>
        <Button size="icon" variant="ghost" type="button" requiresWriteAccess onClick={onDelete} disabled={total === 1} title="Elimina regola" aria-label="Elimina regola"><Trash2 size={15} aria-hidden="true" /></Button>
      </div>
    </article>
  );
}

export { GuardRuleRow };
