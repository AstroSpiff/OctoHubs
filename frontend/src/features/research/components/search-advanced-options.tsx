import { SlidersHorizontal } from "@/components/ui/icons";
import { useState } from "react";

import { csvText, csvValues } from "@/features/research/customization";
import { visibleSortMediaTypes } from "@/features/research/search-advanced-options-presentation";
import type {
  CustomSearchRules,
  ResearchMediaType,
  SortOption,
} from "@/features/research/types";
import { boundedWholeNumberInput } from "@/lib/numeric-input";

type SearchAdvancedOptionsProps = {
  defaultOpen?: boolean;
  mediaType?: ResearchMediaType;
  movieOptions: SortOption[];
  summaryLabel?: string;
  tvOptions: SortOption[];
  value: CustomSearchRules;
  onChange: (value: CustomSearchRules) => void;
};

function SearchAdvancedOptions({
  defaultOpen = false,
  mediaType,
  movieOptions,
  summaryLabel = "Regole locali per questa ricerca",
  tvOptions,
  value,
  onChange,
}: SearchAdvancedOptionsProps) {
  const [open, setOpen] = useState(defaultOpen);
  const rules = value.search_rules;
  const sortMediaTypes = visibleSortMediaTypes(mediaType);
  function updateRules(patch: Partial<CustomSearchRules["search_rules"]>) {
    onChange({ ...value, search_rules: { ...rules, ...patch } });
  }

  return (
    <details
      className="research-advanced-options"
      open={open}
      onToggle={(event) => setOpen(event.currentTarget.open)}
    >
      <summary>
        <SlidersHorizontal size={16} aria-hidden="true" /> {summaryLabel}
      </summary>
      <div className="research-advanced-body">
        <section>
          <h3>Termini di ricerca</h3>
          <div className="research-field-grid research-field-grid--three">
            <TextListField
              label="Lingue per la query"
              value={rules.query_languages}
              placeholder="ita, italian"
              onChange={(next) => updateRules({ query_languages: next })}
            />
            <TextListField
              label="Risoluzioni / termini query"
              value={rules.query_terms}
              placeholder="2160p, webdl"
              onChange={(next) => updateRules({ query_terms: next })}
            />
            <TextListField
              label="Varianti stagione"
              value={rules.season_templates}
              placeholder="S{season02}, {season}x"
              onChange={(next) => updateRules({ season_templates: next })}
            />
            <ToggleField
              label="Prova anche senza lingua"
              checked={Boolean(rules.include_target_lang_base)}
              onChange={(checked) =>
                updateRules({ include_target_lang_base: checked })
              }
            />
          </div>
        </section>
        <section>
          <h3>Filtri risultati</h3>
          <div className="research-field-grid">
            <TextListField
              label="Lingue richieste nei risultati"
              value={value.target_languages}
              placeholder="ita, italian"
              onChange={(next) =>
                onChange({ ...value, target_languages: next })
              }
            />
            <TextListField
              label="Termini filtrati"
              value={rules.filter_terms}
              placeholder="2160p, remux"
              onChange={(next) => updateRules({ filter_terms: next })}
            />
            <TextListField
              label="Tag da escludere"
              value={value.exclude_tags}
              placeholder="cam, ts"
              onChange={(next) => onChange({ ...value, exclude_tags: next })}
            />
            <label>
              Seeders minimi
              <input
                type="number"
                min="0"
                value={rules.min_seeders || 0}
                onChange={(event) =>
                  updateRules({
                    min_seeders: boundedWholeNumberInput(event.target.value, 0),
                  })
                }
              />
            </label>
          </div>
        </section>
        <section>
          <h3>Ordinamento</h3>
          <div className="research-sort-grid">
            {sortMediaTypes.includes("movie") ? <SortFields
              label="Film"
              options={movieOptions}
              primary={rules.movie_sort_primary || ""}
              secondary={rules.movie_sort_secondary || ""}
              onChange={(primary, secondary) =>
                updateRules({
                  movie_sort_primary: primary,
                  movie_sort_secondary: secondary,
                })
              }
            /> : null}
            {sortMediaTypes.includes("tv") ? <SortFields
              label="Serie TV"
              options={tvOptions}
              primary={rules.tv_sort_primary || ""}
              secondary={rules.tv_sort_secondary || ""}
              onChange={(primary, secondary) =>
                updateRules({
                  tv_sort_primary: primary,
                  tv_sort_secondary: secondary,
                })
              }
            /> : null}
          </div>
        </section>
        <section className="research-toggle-grid">
          <h3>Opzioni aggiuntive</h3>
          <ToggleField
            label="Usa titolo originale"
            checked={Boolean(rules.use_original_title)}
            onChange={(checked) => updateRules({ use_original_title: checked })}
          />
          <ToggleField
            label="Usa titoli alternativi originali"
            checked={Boolean(rules.use_alt_titles_original)}
            onChange={(checked) =>
              updateRules({ use_alt_titles_original: checked })
            }
          />
          <label className="research-toggle">
            <input
              type="checkbox"
              checked={Boolean(rules.use_alt_titles_language)}
              onChange={(event) =>
                updateRules({ use_alt_titles_language: event.target.checked })
              }
            />
            <span>Titoli alternativi in lingua</span>
            <select
              aria-label="Lingua titoli alternativi"
              value={rules.alt_titles_language || "all"}
              disabled={!rules.use_alt_titles_language}
              onChange={(event) =>
                updateRules({ alt_titles_language: event.target.value })
              }
            >
              <option value="all">Tutte</option>
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
          <ToggleField
            label="Richiedi lingua audio"
            checked={Boolean(rules.require_audio_language)}
            onChange={(checked) =>
              updateRules({ require_audio_language: checked })
            }
          />
          <ToggleField
            label="Cerca singoli episodi"
            checked={Boolean(rules.search_episode_variants)}
            onChange={(checked) =>
              updateRules({
                search_episode_variants: checked,
                ...(checked
                  ? {}
                  : { skip_season_queries_when_episode_search: false }),
              })
            }
          />
          <ToggleField
            label="Escludi query stagione con ricerca episodi"
            checked={Boolean(rules.skip_season_queries_when_episode_search)}
            disabled={!rules.search_episode_variants}
            onChange={(checked) =>
              updateRules({ skip_season_queries_when_episode_search: checked })
            }
          />
          <ToggleField
            label="Normalizza titoli"
            checked={Boolean(rules.sanitize_titles)}
            onChange={(checked) => updateRules({ sanitize_titles: checked })}
          />
          <ToggleField
            label="Ignora anno per serie TV"
            checked={Boolean(rules.ignore_year_for_tv)}
            onChange={(checked) => updateRules({ ignore_year_for_tv: checked })}
          />
          <ToggleField
            label="Escludi contenuti già disponibili"
            checked={Boolean(rules.skip_available_content)}
            onChange={(checked) =>
              updateRules({ skip_available_content: checked })
            }
          />
          <ToggleField
            label="Escludi contenuti non pubblicati"
            checked={Boolean(rules.skip_unreleased_content)}
            onChange={(checked) =>
              updateRules({ skip_unreleased_content: checked })
            }
          />
        </section>
      </div>
    </details>
  );
}

function TextListField({
  label,
  value,
  placeholder,
  onChange,
}: {
  label: string;
  value: string[] | undefined;
  placeholder: string;
  onChange: (value: string[]) => void;
}) {
  return (
    <label>
      {label}
      <input
        value={csvText(value)}
        placeholder={placeholder}
        onChange={(event) => onChange(csvValues(event.target.value))}
      />
    </label>
  );
}

function ToggleField({
  label,
  checked,
  disabled = false,
  onChange,
}: {
  label: string;
  checked: boolean;
  disabled?: boolean;
  onChange: (checked: boolean) => void;
}) {
  return (
    <label className="research-toggle">
      <input
        type="checkbox"
        checked={checked}
        disabled={disabled}
        onChange={(event) => onChange(event.target.checked)}
      />
      <span>{label}</span>
    </label>
  );
}

function SortFields({
  label,
  options,
  primary,
  secondary,
  onChange,
}: {
  label: string;
  options: SortOption[];
  primary: string;
  secondary: string;
  onChange: (primary: string, secondary: string) => void;
}) {
  const primaryGroup = options.find(
    (option) => option.value === primary,
  )?.group;
  const secondaryGroup = options.find(
    (option) => option.value === secondary,
  )?.group;
  return (
    <fieldset>
      <legend>{label}</legend>
      <label>
        Primo criterio
        <select
          value={primary}
          onChange={(event) => onChange(event.target.value, secondary)}
        >
          {options.map((option) => (
            <option
              key={option.value}
              value={option.value}
              disabled={Boolean(
                secondaryGroup &&
                option.group === secondaryGroup &&
                option.value !== primary,
              )}
            >
              {option.label}
            </option>
          ))}
        </select>
      </label>
      <label>
        Secondo criterio
        <select
          value={secondary}
          onChange={(event) => onChange(primary, event.target.value)}
        >
          <option value="">Nessuno</option>
          {options.map((option) => (
            <option
              key={option.value}
              value={option.value}
              disabled={Boolean(
                primaryGroup &&
                option.group === primaryGroup &&
                option.value !== secondary,
              )}
            >
              {option.label}
            </option>
          ))}
        </select>
      </label>
    </fieldset>
  );
}

export { SearchAdvancedOptions };
