import type { RequestSearchRule } from "@/features/research/types";
import { AlternativeTitleLanguageField } from "@/features/research/components/alternative-title-language-field";
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
    <AlternativeTitleLanguageField
      checked={rule.use_alt_titles_language}
      disabled={disabled}
      label="Titoli alt. lingua"
      language={rule.alt_titles_language}
      onCheckedChange={(checked) => onChange({ use_alt_titles_language: checked })}
      onLanguageChange={(language) => onChange({ alt_titles_language: language })}
    />
    {mediaType !== "tv" ? <label>
      Anno +/-
      <input type="number" min="0" max="10" disabled={disabled} value={rule.year_variance} onChange={(event) => onChange({ year_variance: boundedWholeNumberInput(event.target.value, 0, 10) })} />
    </label> : null}
  </div>;
}

export { RequestRuleFields };
