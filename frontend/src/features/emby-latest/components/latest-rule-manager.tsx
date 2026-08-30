import { Pencil, Plus, Trash2 } from "@/components/ui/icons";
import { useEffect, useState } from "react";

import { Button } from "@/components/ui/button";
import { WriteAction } from "@/features/session/workspace-capabilities";
import { LatestRuleEditor } from "@/features/emby-latest/components/latest-rule-editor";
import {
  copyLatestRuleInput,
  emptyLatestRuleInput,
  latestRuleInputMatches,
} from "@/features/emby-latest/latest-rule-draft";
import type {
  LatestPreset,
  LatestRule,
  LatestRuleInput,
  LatestServer,
  LatestTelegramPreset,
} from "@/features/emby-latest/types";

function LatestRuleManager({
  rules,
  servers,
  presets,
  telegramPresets,
  saving,
  changingId,
  removingId,
  error,
  onSave,
  onToggle,
  onRemove,
  onDirtyChange,
}: {
  rules: LatestRule[];
  servers: LatestServer[];
  presets: LatestPreset[];
  telegramPresets: LatestTelegramPreset[];
  saving: boolean;
  changingId?: string;
  removingId?: string;
  error?: string;
  onSave: (rule: LatestRuleInput) => Promise<unknown>;
  onToggle: (rule: LatestRule) => void;
  onRemove: (rule: LatestRule) => void;
  onDirtyChange?: (dirty: boolean) => void;
}) {
  const [editor, setEditor] = useState<{
    baseline: LatestRuleInput;
    draft: LatestRuleInput;
  } | null>(null);
  const dirty = Boolean(editor && !latestRuleInputMatches(editor.draft, editor.baseline));

  useEffect(() => {
    onDirtyChange?.(dirty);
    return () => onDirtyChange?.(false);
  }, [dirty, onDirtyChange]);

  function openEditor(input: LatestRuleInput) {
    const baseline = copyLatestRuleInput(input);
    setEditor({ baseline, draft: copyLatestRuleInput(baseline) });
  }

  return (
    <section className="latest-config-card latest-rule-manager">
      <header>
        <div>
          <h4>Regole di notifica</h4>
          <p>
            Definisci server, preset e destinazione Telegram per ogni invio.
          </p>
        </div>
        <Button
          type="button"
          requiresWriteAccess
          variant="primary"
          size="compact"
          disabled={saving}
          onClick={() => openEditor(emptyLatestRuleInput())}
        >
          <Plus size={15} aria-hidden="true" />
          Nuova regola
        </Button>
      </header>
      {rules.length ? (
        <div className="latest-config-list">
          {rules.map((rule) => (
            <article className="latest-rule-row" key={rule.id}>
              <div>
                <strong>{rule.name}</strong>
                <p>
                  {rule.server_names?.join(", ") || "Server mancanti"} →{" "}
                  {rule.preset_name || "Preset mancante"} →{" "}
                  {rule.telegram_name || "Telegram mancante"}
                </p>
                {rule.has_missing ? (
                  <small>
                    Attenzione: risorse mancanti ({rule.missing_label}).
                  </small>
                ) : null}
              </div>
              <WriteAction>
                <div className="latest-rule-actions">
                  <label className="latest-switch">
                    <input
                      type="checkbox"
                      checked={rule.enabled}
                      disabled={saving || changingId === rule.id}
                      onChange={() => onToggle(rule)}
                    />
                    <span>{rule.enabled ? "Attiva" : "Disattiva"}</span>
                  </label>
                  <Button
                    type="button"
                    variant="ghost"
                    size="compact"
                    title={`Modifica ${rule.name}`}
                    onClick={() =>
                      openEditor({
                        id: rule.id,
                        name: rule.name,
                        server_ids: rule.server_ids,
                        preset_id: rule.preset_id,
                        telegram_config_id: rule.telegram_config_id,
                      })
                    }
                    disabled={saving}
                  >
                    <Pencil size={15} aria-hidden="true" />
                  </Button>
                  <Button
                    type="button"
                    variant="ghost"
                    size="compact"
                    title={`Elimina ${rule.name}`}
                    disabled={saving || removingId === rule.id}
                    onClick={() => onRemove(rule)}
                  >
                    <Trash2 size={15} aria-hidden="true" />
                  </Button>
                </div>
              </WriteAction>
            </article>
          ))}
        </div>
      ) : (
        <p className="latest-config-empty">
          Nessuna regola salvata. Crea la prima regola per iniziare.
        </p>
      )}
      {editor ? (
        <LatestRuleEditor
          draft={editor.draft}
          baseline={editor.baseline}
          servers={servers}
          presets={presets}
          telegramPresets={telegramPresets}
          saving={saving}
          onChange={(draft) =>
            setEditor((current) =>
              current ? { ...current, draft } : current,
            )
          }
          onCancel={() => setEditor(null)}
          onSave={() => {
            void onSave(editor.draft)
              .then(() => setEditor(null))
              .catch(() => undefined);
          }}
        />
      ) : null}
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
    </section>
  );
}

export { LatestRuleManager };
