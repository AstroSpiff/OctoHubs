import { Check, RotateCcw, Save } from "@/components/ui/icons";
import { useEffect, useMemo, useState } from "react";

import { Button } from "@/components/ui/button";
import { WriteAction } from "@/features/session/workspace-capabilities";
import { saveGlobalSearchRules } from "@/features/research/api";
import { customRulesFromSearchRules } from "@/features/research/customization";
import { SearchAdvancedOptions } from "@/features/research/components/search-advanced-options";
import { useSynchronizedDraft } from "@/lib/use-synchronized-draft";
import type {
  CustomSearchRules,
  ResearchOverview,
  ResearchNotice,
} from "@/features/research/types";

function GlobalSearchRules({
  overview,
  onSaved,
  onDirtyChange,
}: {
  overview: ResearchOverview;
  onSaved: () => void;
  onDirtyChange?: (dirty: boolean) => void;
}) {
  const source = useMemo<CustomSearchRules>(
    () => ({
      ...customRulesFromSearchRules(overview.search_rules),
      target_languages: [...overview.search_defaults.target_languages],
      exclude_tags: [...overview.search_defaults.exclude_tags],
    }),
    [
      overview.search_defaults.exclude_tags,
      overview.search_defaults.target_languages,
      overview.search_rules,
    ],
  );
  const { accept, dirty, discard, draft, setDraft } = useSynchronizedDraft(
    source,
    copyRules,
  );
  const [saving, setSaving] = useState(false);
  const [notice, setNotice] = useState<ResearchNotice | null>(null);

  useEffect(() => {
    onDirtyChange?.(dirty);
  }, [dirty, onDirtyChange]);

  useEffect(
    () => () => onDirtyChange?.(false),
    [onDirtyChange],
  );

  async function save() {
    if (!draft) return;
    setSaving(true);
    setNotice(null);
    try {
      const response = await saveGlobalSearchRules(draft);
      if (response.success) accept(draft, draft);
      setNotice({
        message: response.message || "Regole di ricerca aggiornate.",
        tone: response.success ? "success" : "error",
      });
      if (response.success) onSaved();
    } catch (reason) {
      setNotice({
        message:
          reason instanceof Error
            ? reason.message
            : "Salvataggio delle regole non riuscito.",
        tone: "error",
      });
    } finally {
      setSaving(false);
    }
  }

  const estimate = overview.variant_estimate;
  if (!draft) return null;
  return (
    <section
      className="research-card"
      aria-labelledby="global-search-rules-title"
    >
      <header className="research-card-heading">
        <div>
          <h3 id="global-search-rules-title" className="contextual-heading" title="Configurazione condivisa">Impostazioni globali</h3>
          <p>
            Queste regole guidano le ricerche automatiche e i valori iniziali
            della ricerca indipendente.
          </p>
        </div>
      </header>
      <WriteAction>
        <div className="global-search-rules-body">
        <fieldset className="global-search-rules-editable" disabled={saving}>
          <SearchAdvancedOptions
            defaultOpen
            summaryLabel="Regole di ricerca"
            value={draft}
            onChange={setDraft}
            movieOptions={overview.movie_sort_options}
            tvOptions={overview.tv_sort_options}
          />
        </fieldset>
        {estimate ? (
          <p className="research-variant-estimate">
            Questa configurazione genera circa {estimate.base || 0} combinazioni
            per titolo o stagione
            {estimate.episodes
              ? `, più circa ${estimate.episodes} query per episodio`
              : ""}
            .
          </p>
        ) : null}
        {dirty ? (
          <div className="research-draft-state" role="status">
            <span>Modifiche non salvate</span>
            <Button
              type="button"
              variant="ghost"
              size="compact"
              disabled={saving}
              onClick={discard}
            >
              <RotateCcw size={14} aria-hidden="true" /> Ripristina
            </Button>
          </div>
        ) : null}
        {notice ? (
          <div
            className={`inline-alert inline-alert--${notice.tone}`}
            role={notice.tone === "error" ? "alert" : "status"}
          >
            {notice.tone === "success" ? (
              <Check size={16} aria-hidden="true" />
            ) : null}
            {notice.message}
          </div>
        ) : null}
        <footer className="research-card-actions">
          <Button
            type="button"
            variant="primary"
            onClick={() => void save()}
            disabled={saving || !dirty}
          >
            {saving ? (
              "Salvataggio..."
            ) : (
              <>
                <Save size={16} aria-hidden="true" /> Salva regole
              </>
            )}
          </Button>
        </footer>
        </div>
      </WriteAction>
    </section>
  );
}

function copyRules(value: CustomSearchRules): CustomSearchRules {
  return {
    ...value,
    search_rules: { ...value.search_rules },
    target_languages: [...value.target_languages],
    exclude_tags: [...value.exclude_tags],
  };
}

export { GlobalSearchRules };
