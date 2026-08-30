import { MessageSquareText } from "@/components/ui/icons";

import { messagesEnabled } from "@/features/transcode-guard-settings/rule-model";
import type { GuardRule } from "@/features/transcode-guard-settings/types";
import { boundedWholeNumberInput } from "@/lib/numeric-input";

function RuleMessageFields({ rule, onChange }: { rule: GuardRule; onChange: (changes: Partial<GuardRule>) => void }) {
  const enabled = messagesEnabled(rule);
  return (
    <details className="rule-editor-details">
      <summary><MessageSquareText size={17} aria-hidden="true" /> Messaggi e tempi</summary>
      {!enabled ? <p className="rule-editor-empty">Questa regola non invia messaggi con l'intervento selezionato.</p> : null}
      <div className="rule-editor-details-content" aria-disabled={!enabled}>
        <div className="rule-editor-grid rule-editor-grid--three">
          <label className="guard-setting-field"><span>Visualizzazione</span><select disabled={!enabled} value={rule.message_display_mode} onChange={(event) => onChange({ message_display_mode: event.target.value as GuardRule["message_display_mode"] })}><option value="toast">Avviso temporaneo</option><option value="confirmation">Conferma</option></select></label>
          <label className="guard-setting-field"><span>Numero massimo avvisi</span><input disabled={!enabled} type="number" min="1" max="10" value={rule.max_warnings} onChange={(event) => onChange({ max_warnings: boundedWholeNumberInput(event.target.value, 1, 10) })} /></label>
          <label className="guard-setting-field"><span>Attesa tra avvisi</span><input disabled={!enabled} type="number" min="0" max="3600" value={rule.message_cooldown_seconds} onChange={(event) => onChange({ message_cooldown_seconds: boundedWholeNumberInput(event.target.value, 0, 3600) })} /></label>
        </div>
        <div className="rule-editor-grid rule-editor-grid--two">
          <label className="guard-setting-field"><span>Durata avviso (millisecondi)</span><input disabled={!enabled || rule.message_display_mode === "confirmation"} type="number" min="1000" max="300000" value={rule.warning_timeout_ms} onChange={(event) => onChange({ warning_timeout_ms: boundedWholeNumberInput(event.target.value, 1000, 300000) })} /></label>
          <label className="guard-setting-field"><span>Attesa prima dello stop (secondi)</span><input disabled={rule.mode !== "warn_then_stop"} type="number" min="0" max="1800" value={rule.correction_window_seconds} onChange={(event) => onChange({ correction_window_seconds: boundedWholeNumberInput(event.target.value, 0, 1800) })} /></label>
        </div>
        <label className="guard-setting-field"><span>Titolo messaggio</span><input disabled={!enabled} value={rule.message_header} onChange={(event) => onChange({ message_header: event.target.value })} /></label>
        <label className="guard-setting-field"><span>Testo messaggio</span><textarea disabled={!enabled} rows={4} value={rule.message_text} onChange={(event) => onChange({ message_text: event.target.value })} /></label>
      </div>
    </details>
  );
}

export { RuleMessageFields };
