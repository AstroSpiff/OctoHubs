import { BookOpenText, Pencil, Plus, Trash2 } from "@/components/ui/icons";
import { useEffect, useRef, useState } from "react";

import { Button } from "@/components/ui/button";
import { WriteAction } from "@/features/session/workspace-capabilities";
import { useConfirmationDialog } from "@/components/ui/use-confirmation-dialog";
import { LatestTemplateTokenDialog } from "@/features/emby-latest/components/latest-template-token-dialog";
import {
  copyLatestPresetInput,
  emptyLatestPresetInput,
  latestPresetInputFromPreset,
  latestPresetInputMatches,
} from "@/features/emby-latest/latest-preset-draft";
import type { LatestPreset, LatestPresetInput } from "@/features/emby-latest/types";

const quickTokens = [
  "{{ title }}",
  "{{ year }}",
  "{{ overview }}",
  "{{ rating }}",
  "{{ imdb_url }}",
  "{{ tmdb_url }}",
  "{{ trakt_url }}",
  "{{ cast_3 }}",
];

function LatestPresetManager({
  presets,
  saving,
  removingId,
  onSave,
  onRemove,
  onTemplateChange,
  onDirtyChange,
  error,
}: {
  presets: LatestPreset[];
  saving: boolean;
  removingId?: string;
  onSave: (preset: LatestPresetInput) => Promise<unknown>;
  onRemove: (preset: LatestPreset) => void;
  onTemplateChange: (template: string) => void;
  onDirtyChange?: (dirty: boolean) => void;
  error?: string;
}) {
  const confirmation = useConfirmationDialog();
  const [draft, setDraft] = useState<LatestPresetInput>(emptyLatestPresetInput);
  const [baseline, setBaseline] = useState<LatestPresetInput>(emptyLatestPresetInput);
  const [tokenDialogOpen, setTokenDialogOpen] = useState(false);
  const templateRef = useRef<HTMLTextAreaElement>(null);
  const editing = Boolean(draft.id);
  const dirty = !latestPresetInputMatches(draft, baseline);

  useEffect(
    () => onTemplateChange(draft.template),
    [draft.template, onTemplateChange],
  );

  useEffect(() => {
    onDirtyChange?.(dirty);
    return () => onDirtyChange?.(false);
  }, [dirty, onDirtyChange]);

  function accept(next: LatestPresetInput) {
    const copy = copyLatestPresetInput(next);
    setBaseline(copy);
    setDraft(copyLatestPresetInput(copy));
  }

  async function selectDraft(next: LatestPresetInput) {
    if (dirty && !await confirmation.confirm({ title: "Preset non salvato", description: "Sostituire e perdere le modifiche al preset?", confirmLabel: "Abbandona modifiche", tone: "danger" })) return;
    accept(next);
  }

  function insertToken(token: string) {
    const input = templateRef.current;
    const start = input?.selectionStart ?? draft.template.length;
    const end = input?.selectionEnd ?? start;
    setDraft((current) => ({
      ...current,
      template: `${current.template.slice(0, start)}${token}${current.template.slice(end)}`,
    }));
    setTokenDialogOpen(false);
    window.requestAnimationFrame(() => {
      input?.focus();
      input?.setSelectionRange(start + token.length, start + token.length);
    });
  }

  return (
    <section className="latest-config-card latest-preset-manager">
      <header>
        <h4>Gestione preset</h4>
        <p>
          Il template definisce testo, formattazione e collegamenti della
          notifica.
        </p>
      </header>
      <WriteAction>
        <form
          onSubmit={(event) => {
            event.preventDefault();
            void onSave(draft)
              .then(() => accept(emptyLatestPresetInput()))
              .catch(() => undefined);
          }}
          className="latest-form"
        >
        <label>
          Nome preset
          <input
            required
            value={draft.name}
            disabled={saving}
            onChange={(event) =>
              setDraft((current) => ({ ...current, name: event.target.value }))
            }
            placeholder="Notifiche Emby"
          />
        </label>
        <label>
          Template messaggio
          <textarea
            ref={templateRef}
            required
            rows={10}
            value={draft.template}
            disabled={saving}
            onChange={(event) =>
              setDraft((current) => ({
                ...current,
                template: event.target.value,
              }))
            }
            placeholder="Usa i pattern disponibili per comporre il messaggio."
          />
        </label>
        <div className="latest-token-help">
          <div className="latest-token-help-header">
            <strong>Pattern messaggio</strong>
            <Button type="button" variant="ghost" size="compact" onClick={() => setTokenDialogOpen(true)} disabled={saving}>
              <BookOpenText size={15} aria-hidden="true" />
              Catalogo completo
            </Button>
          </div>
          <p>
            Sintassi Jinja2 e i vecchi pattern <code>{"{title}"}</code>{" "}
            sono compatibili. I token rapidi restano qui, il catalogo contiene tutti i campi disponibili.
          </p>
          <div className="latest-token-quick-list">
            {quickTokens.map((token) => (
              <button
                type="button"
                key={token}
                onClick={() => insertToken(token)}
                disabled={saving}
              >
                {token}
              </button>
            ))}
          </div>
        </div>
        <div className="latest-form-actions">
          <Button type="submit" variant="primary" disabled={saving}>
            {editing ? (
              <Pencil size={15} aria-hidden="true" />
            ) : (
              <Plus size={15} aria-hidden="true" />
            )}
            {editing ? "Aggiorna preset" : "Salva preset"}
          </Button>
          {editing ? (
            <Button type="button" variant="ghost" onClick={() => void selectDraft(emptyLatestPresetInput())} disabled={saving}>
              Annulla
            </Button>
          ) : null}
        </div>
        </form>
      </WriteAction>
      <div className="latest-config-list">
        {presets.map((preset) => (
          <article key={preset.id} className="latest-config-row">
            <div>
              <strong>{preset.name}</strong>
              <p>{preset.template}</p>
            </div>
            <div>
              <Button
                type="button"
                requiresWriteAccess
                variant="ghost"
                size="compact"
                title={`Modifica ${preset.name}`}
                onClick={() => void selectDraft(latestPresetInputFromPreset(preset))}
                disabled={saving}
              >
                <Pencil size={15} aria-hidden="true" />
              </Button>
              <Button
                type="button"
                requiresWriteAccess
                variant="ghost"
                size="compact"
                title={`Rimuovi ${preset.name}`}
                disabled={saving || removingId === preset.id}
                onClick={() => onRemove(preset)}
              >
                <Trash2 size={15} aria-hidden="true" />
              </Button>
            </div>
          </article>
        ))}
      </div>
      {saving ? (
        <p className="latest-form-status" role="status">
          Salvataggio configurazione in corso...
        </p>
      ) : null}
      {error ? (
        <p className="latest-form-error" role="alert">
          {error}
        </p>
      ) : null}
      <LatestTemplateTokenDialog
        open={tokenDialogOpen}
        onClose={() => setTokenDialogOpen(false)}
        onSelect={insertToken}
      />
      {confirmation.dialog}
    </section>
  );
}

export { LatestPresetManager };
