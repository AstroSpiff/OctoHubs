import { Clock3 } from "@/components/ui/icons";
import type { ReactNode } from "react";

import type { AutomationTask } from "@/features/configuration/types";
import { boundedWholeNumberInput } from "@/lib/numeric-input";

function AutomationTaskEditor({ title, description, value, onChange, supplement }: { title: string; description: string; value: AutomationTask; onChange: (value: AutomationTask) => void; supplement?: ReactNode }) {
  function update(patch: Partial<AutomationTask>) {
    onChange({ ...value, ...patch });
  }

  return <section className="automation-task">
    <header>
      <div><h3>{title}</h3><p>{description}</p></div>
      <label className="configuration-switch"><input type="checkbox" checked={value.enabled} onChange={(event) => update({ enabled: event.target.checked })} /><span>Attiva</span></label>
    </header>
    <div className="automation-task-options">
      <label><input type="radio" name={`${title}-mode`} checked={value.mode === "interval"} onChange={() => update({ mode: "interval" })} /> Avvia ogni</label>
      <input aria-label={`${title}, intervallo in minuti`} type="number" min="5" value={value.interval_minutes} disabled={!value.enabled || value.mode !== "interval"} onChange={(event) => update({ interval_minutes: boundedWholeNumberInput(event.target.value, 5) })} />
      <span>minuti</span>
    </div>
    <div className="automation-task-options automation-task-options--fixed">
      <label><input type="radio" name={`${title}-mode`} checked={value.mode === "fixed"} onChange={() => update({ mode: "fixed" })} /> Orari fissi</label>
      <input aria-label={`${title}, orari fissi`} type="text" placeholder="08:00, 22:30" value={value.times.join(", ")} disabled={!value.enabled || value.mode !== "fixed"} onChange={(event) => update({ times: event.target.value.split(",").map((item) => item.trim()).filter(Boolean) })} />
    </div>
    <p className="automation-task-note"><Clock3 size={14} aria-hidden="true" /> {value.mode === "fixed" ? "Usa orari nel formato HH:MM, separati da virgole." : "L'esecuzione successiva viene calcolata dall'ultimo completamento."}</p>
    {supplement}
  </section>;
}

export { AutomationTaskEditor };
