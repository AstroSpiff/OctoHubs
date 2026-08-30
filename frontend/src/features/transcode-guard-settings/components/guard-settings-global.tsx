import { Clock3, Database, Power } from "@/components/ui/icons";

import { Card } from "@/components/ui/card";
import type { TranscodeGuardSettings } from "@/features/transcode-guard-settings/types";
import { boundedWholeNumberInput } from "@/lib/numeric-input";

function GuardSettingsGlobal({ settings, onChange }: { settings: TranscodeGuardSettings; onChange: (changes: Partial<TranscodeGuardSettings>) => void }) {
  return (
    <Card className="guard-settings-global">
      <div className="guard-settings-global-copy">
        <span><Power size={20} aria-hidden="true" /></span>
        <div><h4 className="contextual-heading" title="Politica">Monitor automatico</h4><small>Le modifiche si applicano solo dopo il salvataggio.</small></div>
      </div>
      <label className="guard-settings-switch"><input type="checkbox" checked={settings.enabled} onChange={(event) => onChange({ enabled: event.target.checked })} /><span>Attivo</span></label>
      <div className="guard-settings-global-fields">
        <label><span><Clock3 size={15} aria-hidden="true" /> Intervallo verifica</span><input type="number" min="2" max="120" value={settings.poll_interval_seconds} onChange={(event) => onChange({ poll_interval_seconds: boundedWholeNumberInput(event.target.value, 2, 120) })} /><small>secondi</small></label>
        <label><span><Database size={15} aria-hidden="true" /> Conservazione storico</span><input type="number" min="0" max="3650" value={settings.stream_history_retention_days} onChange={(event) => onChange({ stream_history_retention_days: boundedWholeNumberInput(event.target.value, 0, 3650) })} /><small>giorni, 0 conserva tutto</small></label>
      </div>
    </Card>
  );
}

export { GuardSettingsGlobal };
