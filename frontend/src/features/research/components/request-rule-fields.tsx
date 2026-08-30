import type { RequestSearchRule } from "@/features/research/types";
import { boundedWholeNumberInput } from "@/lib/numeric-input";

function RequestRuleFields({
  rule,
  mediaType,
  disabled,
  onChange,
}: {
  rule: RequestSearchRule;
  mediaType: string;
  disabled: boolean;
  onChange: (patch: Partial<RequestSearchRule>) => void;
}) {
  return <div className="research-request-rule-fields">
    <label>
      Termini query
      <input value={rule.query_terms} disabled={disabled} onChange={(event) => onChange({ query_terms: event.target.value })} />
    </label>
    <label>
      Termini filtrati
      <input value={rule.filter_terms} disabled={disabled} onChange={(event) => onChange({ filter_terms: event.target.value })} />
    </label>
    <label>
      Termini esclusi
      <input value={rule.exclude_terms} disabled={disabled} onChange={(event) => onChange({ exclude_terms: event.target.value })} />
    </label>
    <label className="research-toggle">
      <input type="checkbox" checked={rule.use_original_title} disabled={disabled} onChange={(event) => onChange({ use_original_title: event.target.checked })} />
      <span>Titolo originale</span>
    </label>
    <label className="research-toggle">
      <input type="checkbox" checked={rule.use_alt_titles_original} disabled={disabled} onChange={(event) => onChange({ use_alt_titles_original: event.target.checked })} />
      <span>Titoli alt. originali</span>
    </label>
    <label className="research-toggle">
      <input type="checkbox" checked={rule.use_alt_titles_language} disabled={disabled} onChange={(event) => onChange({ use_alt_titles_language: event.target.checked })} />
      <span>Titoli alt. lingua</span>
      <select aria-label="Lingua titoli alternativi" disabled={disabled || !rule.use_alt_titles_language} value={rule.alt_titles_language} onChange={(event) => onChange({ alt_titles_language: event.target.value })}>
        <option value="it">IT</option>
        <option value="en">EN</option>
        <option value="es">ES</option>
        <option value="fr">FR</option>
        <option value="de">DE</option>
        <option value="pt">PT</option>
        <option value="ru">RU</option>
        <option value="ja">JA</option>
        <option value="ko">KO</option>
        <option value="zh">ZH</option>
        <option value="ar">AR</option>
      </select>
    </label>
    {mediaType !== "tv" ? <label>
      Anno +/-
      <input type="number" min="0" max="10" disabled={disabled} value={rule.year_variance} onChange={(event) => onChange({ year_variance: boundedWholeNumberInput(event.target.value, 0, 10) })} />
    </label> : null}
  </div>;
}

export { RequestRuleFields };
