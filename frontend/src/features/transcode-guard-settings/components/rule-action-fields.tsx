import type { GuardRule, GuardMode } from "@/features/transcode-guard-settings/types";

function RuleActionFields({ rule, onChange }: { rule: GuardRule; onChange: (changes: Partial<GuardRule>) => void }) {
  return (
    <section className="rule-editor-section">
      <h5>Intervento</h5>
      <div className="rule-editor-grid rule-editor-grid--three">
        <label className="guard-setting-field"><span>Azione</span><select value={rule.mode} onChange={(event) => onChange({ mode: event.target.value as GuardMode })}><option value="monitor">Solo monitoraggio</option><option value="warn">Avvisa soltanto</option><option value="warn_then_stop">Avvisa, attendi e ferma</option><option value="stop">Ferma subito</option></select></label>
        <label className="guard-setting-field"><span>Soglia qualità</span><select value={rule.min_source_height} onChange={(event) => onChange({ min_source_height: Number(event.target.value) })}><option value="0">Nessuna soglia</option>{[2160, 1440, 1080, 720, 576, 480].map((height) => <option key={height} value={height}>{height}p+</option>)}</select></label>
        <label className="guard-setting-switch guard-setting-switch--field"><input type="checkbox" checked={rule.ignore_paused} onChange={(event) => onChange({ ignore_paused: event.target.checked })} /><span>Ignora riproduzioni in pausa</span></label>
      </div>
    </section>
  );
}

export { RuleActionFields };
