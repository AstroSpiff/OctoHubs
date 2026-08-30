import type { GuardRule, PresenceState, StreamState } from "@/features/transcode-guard-settings/types";

const streamOptions: Array<[StreamState, string]> = [["any", "Qualsiasi"], ["transcode", "Transcodifica"], ["direct", "Diretto"]];
const presenceOptions: Array<[PresenceState, string]> = [["any", "Qualsiasi"], ["present", "Presente"], ["absent", "Assente"]];

function RuleMatchingFields({ rule, onChange }: { rule: GuardRule; onChange: (changes: Partial<GuardRule>) => void }) {
  return (
    <section className="rule-editor-section">
      <h5>Condizioni tecniche</h5>
      <div className="rule-editor-grid rule-editor-grid--four">
        <SelectField label="Video" value={rule.video_state} options={streamOptions} onChange={(value) => onChange({ video_state: value as StreamState })} />
        <SelectField label="Audio" value={rule.audio_state} options={streamOptions} onChange={(value) => onChange({ audio_state: value as StreamState })} />
        <SelectField label="Remux" value={rule.remux_state} options={presenceOptions} onChange={(value) => onChange({ remux_state: value as PresenceState })} />
        <SelectField label="Trasformazione" value={rule.transformation_state} options={presenceOptions} onChange={(value) => onChange({ transformation_state: value as PresenceState })} />
      </div>
      <div className="rule-editor-toggle-grid">
        <label className="guard-setting-switch guard-setting-switch--field" title="Lascia passare gli stream in cui viene transcodificato solo l'audio.">
          <input type="checkbox" checked={rule.allow_audio_only_transcode} onChange={(event) => onChange({ allow_audio_only_transcode: event.target.checked })} />
          <span>Consenti transcodifica solo audio</span>
        </label>
        <label className="guard-setting-switch guard-setting-switch--field" title="Lascia passare i direct stream che richiedono solo il remux del contenitore.">
          <input type="checkbox" checked={rule.allow_container_remux} onChange={(event) => onChange({ allow_container_remux: event.target.checked })} />
          <span>Consenti remux contenitore</span>
        </label>
      </div>
    </section>
  );
}

function SelectField({ label, value, options, onChange }: { label: string; value: string; options: Array<[string, string]>; onChange: (value: string) => void }) {
  return <label className="guard-setting-field"><span>{label}</span><select value={value} onChange={(event) => onChange(event.target.value)}>{options.map(([key, text]) => <option key={key} value={key}>{text}</option>)}</select></label>;
}

export { RuleMatchingFields };
