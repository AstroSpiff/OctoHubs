import { Check, RefreshCw, Save } from "@/components/ui/icons";
import { useEffect, useState } from "react";

import { Button } from "@/components/ui/button";
import { WorkspaceHeading } from "@/components/ui/workspace-heading";
import { AutomationTaskEditor } from "@/features/configuration/components/automation-task-editor";
import { RequestRefreshStatus } from "@/features/configuration/components/request-refresh-status";
import { useWorkspaceCapabilities } from "@/features/session/workspace-capabilities-context";
import type { ConfigurationAutomations, RequestRefreshStatus as RequestRefreshStatusValue } from "@/features/configuration/types";
import { useSynchronizedDraft } from "@/lib/use-synchronized-draft";

const taskCopy = {
  scan: ["Ricerca programmata", "Esegue la ricerca delle richieste configurate."],
  refresh: ["Aggiornamento richieste", "Ricarica richieste, disponibilità e stato Trakt."],
  workflow: ["Workflow automatico", "Esegue scansione, analisi, cache e notifiche Telegram."],
  sync: ["Sincronizzazione utenti", "Sincronizza lo stato di visione dei gruppi abilitati."],
  collections: ["Collezioni Emby", "Ricarica le fonti e aggiorna le collezioni abilitate."],
} as const;

function AutomationsPanel({ automations, requestRefresh, saving, savedMessage, onSave, onRefresh, onDirtyChange }: { automations?: ConfigurationAutomations; requestRefresh?: RequestRefreshStatusValue; saving: boolean; savedMessage: string; onSave: (value: ConfigurationAutomations) => Promise<ConfigurationAutomations>; onRefresh: () => void; onDirtyChange?: (dirty: boolean) => void }) {
  const { canMutate } = useWorkspaceCapabilities();
  const { accept, dirty, discard, draft, setDraft } = useSynchronizedDraft(automations, copyAutomations);
  const [saveError, setSaveError] = useState("");

  useEffect(() => {
    onDirtyChange?.(dirty);
    return () => onDirtyChange?.(false);
  }, [dirty, onDirtyChange]);

  if (!draft) return <div className="loading-state">Caricamento automazioni...</div>;
  return <section className="configuration-panel" aria-labelledby="configuration-automations-title">
    <WorkspaceHeading level="section" context="Pianificazione" titleId="configuration-automations-title" title="Automazioni" description="Ogni processo può essere disattivato, pianificato a intervallo oppure in orari precisi." actions={<Button type="button" variant="ghost" size="icon" title="Ricarica automazioni" aria-label="Ricarica automazioni" onClick={onRefresh} disabled={saving}><RefreshCw size={16} aria-hidden="true" /></Button>} />
    {savedMessage ? <div className="inline-alert inline-alert--success" role="status"><Check size={17} aria-hidden="true" />{savedMessage}</div> : null}
    {saveError ? <div className="inline-alert inline-alert--error" role="alert">{saveError}</div> : null}
    {!canMutate ? <AutomationSummary automations={draft} requestRefresh={requestRefresh} /> : null}
    {canMutate ? <>
    {dirty ? <div className="configuration-draft-state" role="status"><span>Modifiche non salvate</span><Button type="button" variant="ghost" size="compact" onClick={discard} disabled={saving}>Ripristina valori salvati</Button></div> : null}
    <fieldset className="configuration-editable-fields" disabled={saving}>
      <div className="automation-grid">
        {(Object.keys(taskCopy).filter((id) => id !== "collections") as Array<keyof typeof draft.tasks>).map((taskId) => <AutomationTaskEditor key={taskId} title={taskCopy[taskId][0]} description={taskCopy[taskId][1]} value={draft.tasks[taskId]} onChange={(value) => setDraft((current) => current ? { ...current, tasks: { ...current.tasks, [taskId]: value } } : current)} supplement={taskId === "refresh" ? <RequestRefreshStatus status={requestRefresh} /> : undefined} />)}
        <AutomationTaskEditor title={taskCopy.collections[0]} description={taskCopy.collections[1]} value={draft.collections} onChange={(value) => setDraft((current) => current ? { ...current, collections: value } : current)} />
      </div>
    </fieldset>
    <footer className="configuration-panel-actions"><Button type="button" variant="primary" size="compact" onClick={() => void save()} disabled={saving || !dirty}><Save size={16} aria-hidden="true" />{saving ? "Salvataggio..." : "Salva automazioni"}</Button></footer>
    </> : null}
  </section>;

  async function save() {
    if (!draft) return;
    setSaveError("");
    try {
      accept(await onSave(draft), draft);
    } catch (error) {
      setSaveError(error instanceof Error ? error.message : "Impossibile salvare le automazioni.");
    }
  }
}

function AutomationSummary({ automations, requestRefresh }: { automations: ConfigurationAutomations; requestRefresh?: RequestRefreshStatusValue }) {
  const entries = [
    ...Object.entries(automations.tasks).map(([id, task]) => ({ id, task, title: taskCopy[id as keyof typeof automations.tasks][0] })),
    { id: "collections", task: automations.collections, title: taskCopy.collections[0] },
  ];
  return <div className="automation-grid">{entries.map(({ id, task, title }) => <section className="automation-task" key={id}><header><div><h3>{title}</h3><p>{task.enabled ? task.mode === "fixed" ? `Orari: ${task.times.join(", ") || "non impostati"}` : `Ogni ${task.interval_minutes} minuti` : "Disattivata"}</p></div><span className="configuration-state">{task.enabled ? "Attiva" : "Disattiva"}</span></header>{id === "refresh" ? <RequestRefreshStatus status={requestRefresh} /> : null}</section>)}</div>;
}

function copyAutomations(value: ConfigurationAutomations): ConfigurationAutomations {
  return {
    tasks: Object.fromEntries(Object.entries(value.tasks).map(([id, task]) => [id, { ...task, times: [...task.times] }])) as ConfigurationAutomations["tasks"],
    collections: { ...value.collections, times: [...value.collections.times] },
  };
}

export { AutomationsPanel };
