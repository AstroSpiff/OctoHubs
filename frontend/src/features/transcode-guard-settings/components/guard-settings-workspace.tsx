import { useEffect, useMemo, useState } from "react";

import { GuardRuleEditor } from "@/features/transcode-guard-settings/components/guard-rule-editor";
import { GuardRuleList } from "@/features/transcode-guard-settings/components/guard-rule-list";
import { GuardSettingsGlobal } from "@/features/transcode-guard-settings/components/guard-settings-global";
import { GuardSettingsSave } from "@/features/transcode-guard-settings/components/guard-settings-save";
import { createGuardRule, duplicateGuardRule, validationMessage } from "@/features/transcode-guard-settings/rule-model";
import type { GuardRule, TranscodeGuardSettings } from "@/features/transcode-guard-settings/types";
import { useTranscodeGuardSettings } from "@/features/transcode-guard-settings/use-transcode-guard-settings";
import { useConfirmationDialog } from "@/components/ui/use-confirmation-dialog";
import { WorkspaceHeading } from "@/components/ui/workspace-heading";
import { WorkspaceSection } from "@/components/ui/workspace-layout";
import { WriteAction } from "@/features/session/workspace-capabilities";
import { useBeforeUnloadWarning } from "@/lib/use-before-unload-warning";
import { useUnsavedChangesNavigationGuard } from "@/lib/use-unsaved-changes-navigation-guard";

function GuardSettingsWorkspace({ embedded = true }: { embedded?: boolean }) {
  const { settings, draft, dirty, notice, save, updateDraft } = useTranscodeGuardSettings();
  const confirmation = useConfirmationDialog();
  useBeforeUnloadWarning(dirty);
  useUnsavedChangesNavigationGuard(dirty, confirmation.confirm);
  const [selectedId, setSelectedId] = useState("");
  const [validationError, setValidationError] = useState("");
  const selectedRule = useMemo(() => draft?.rules.find((rule) => rule.id === selectedId), [draft?.rules, selectedId]);
  const selectedIndex = draft?.rules.findIndex((rule) => rule.id === selectedId) ?? -1;

  useEffect(() => {
    if (draft?.rules.length && !draft.rules.some((rule) => rule.id === selectedId)) setSelectedId(draft.rules[0].id);
  }, [draft?.rules, selectedId]);

  function updateSettings(changes: Partial<TranscodeGuardSettings>) {
    updateDraft((current) => ({ ...current, ...changes }));
  }

  function updateRule(id: string, changes: Partial<GuardRule>) {
    updateDraft((current) => ({
      ...current,
      rules: current.rules.map((rule) => rule.id === id ? { ...rule, ...changes } : rule),
    }));
  }

  function addRule() {
    const rule = createGuardRule();
    updateDraft((current) => ({ ...current, rules: [...current.rules, rule] }));
    setSelectedId(rule.id);
  }

  function moveRule(id: string, direction: number) {
    const index = draft?.rules.findIndex((rule) => rule.id === id) ?? -1;
    const target = index + direction;
    if (!draft || index < 0 || target < 0 || target >= draft.rules.length) return;
    updateDraft((current) => {
      const rules = [...current.rules];
      [rules[index], rules[target]] = [rules[target], rules[index]];
      return { ...current, rules };
    });
  }

  function duplicateRule(id: string) {
    updateDraft((current) => {
      const index = current.rules.findIndex((rule) => rule.id === id);
      if (index < 0) return current;
      const rule = duplicateGuardRule(current.rules[index]);
      const rules = [...current.rules];
      rules.splice(index + 1, 0, rule);
      setSelectedId(rule.id);
      return { ...current, rules };
    });
  }

  function deleteRule(id: string) {
    if (!draft || draft.rules.length === 1) return;
    updateDraft((current) => {
      const rules = current.rules.filter((rule) => rule.id !== id);
      if (id === selectedId) setSelectedId(rules[0]?.id || "");
      return { ...current, rules };
    });
  }

  function saveSettings() {
    if (!draft) return;
    const error = validationMessage(draft);
    setValidationError(error);
    if (!error) save.mutate(draft);
  }

  return (
    <WorkspaceSection className="guard-settings-panel" aria-labelledby="guard-rules-title">
      <WorkspaceHeading
        level={embedded ? "subsection" : "section"}
        title="Regole Transcode Guard"
        titleId="guard-rules-title"
        description="Imposta la politica del monitor e l&apos;ordine con cui le regole vengono valutate durante la riproduzione."
        actions={<GuardSettingsSave dirty={dirty} saving={save.isPending} onSave={saveSettings} />}
      />

      {settings.error ? <div className="inline-alert inline-alert--error" role="alert">{settings.error.message}</div> : null}
      {save.error ? <div className="inline-alert inline-alert--error" role="alert">{save.error.message}</div> : null}
      {validationError ? <div className="inline-alert inline-alert--error" role="alert">{validationError}</div> : null}
      {notice ? <div className="inline-alert inline-alert--success" role="status">{notice}</div> : null}
      {settings.isLoading || !draft ? <div className="loading-state">Caricamento regole Transcode Guard...</div> : null}
      {draft ? (
        <WriteAction>
          <fieldset className="guard-settings-editable" disabled={save.isPending}>
            <GuardSettingsGlobal settings={draft} onChange={updateSettings} />
            <div className="guard-settings-workspace">
              <GuardRuleList
                rules={draft.rules}
                selectedId={selectedId}
                onSelect={setSelectedId}
                onAdd={addRule}
                onMove={moveRule}
                onToggle={(id) => updateRule(id, { enabled: !draft.rules.find((rule) => rule.id === id)?.enabled })}
                onDuplicate={duplicateRule}
                onDelete={deleteRule}
              />
              <GuardRuleEditor
                rule={selectedRule}
                index={selectedIndex}
                servers={settings.data?.servers || []}
                onChange={(changes) => selectedRule && updateRule(selectedRule.id, changes)}
              />
            </div>
          </fieldset>
        </WriteAction>
      ) : null}
      {confirmation.dialog}
    </WorkspaceSection>
  );
}

export { GuardSettingsWorkspace };
