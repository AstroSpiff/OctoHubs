import { X } from "@/components/ui/icons";
import { Link } from "react-router-dom";

import { Button } from "@/components/ui/button";
import { DialogBackdrop } from "@/components/ui/dialog-backdrop";
import { useConfirmationDialog } from "@/components/ui/use-confirmation-dialog";
import { latestRuleInputMatches } from "@/features/emby-latest/latest-rule-draft";
import type {
  LatestPreset,
  LatestRuleInput,
  LatestServer,
  LatestTelegramPreset,
} from "@/features/emby-latest/types";

type LatestRuleEditorProps = {
  draft: LatestRuleInput;
  baseline: LatestRuleInput;
  servers: LatestServer[];
  presets: LatestPreset[];
  telegramPresets: LatestTelegramPreset[];
  saving: boolean;
  onChange: (value: LatestRuleInput) => void;
  onCancel: () => void;
  onSave: () => void;
};

function LatestRuleEditor({
  draft,
  baseline,
  servers,
  presets,
  telegramPresets,
  saving,
  onChange,
  onCancel,
  onSave,
}: LatestRuleEditorProps) {
  const confirmation = useConfirmationDialog();
  const dirty = !latestRuleInputMatches(draft, baseline);

  async function requestClose() {
    if (saving) return;
    if (!dirty) {
      onCancel();
      return;
    }
    const confirmed = await confirmation.confirm({
      title: "Regola non salvata",
      description: "Chiudere e perdere le modifiche alla regola?",
      confirmLabel: "Abbandona modifiche",
      tone: "danger",
    });
    if (confirmed) onCancel();
  }

  return (
    <>
      <DialogBackdrop
        className="latest-modal-backdrop"
        dismissible={!saving}
        onDismiss={() => void requestClose()}
      >
        <form
          className="latest-rule-editor"
          role="dialog"
          aria-modal="true"
          aria-labelledby="latest-rule-editor-title"
          onSubmit={(event) => {
            event.preventDefault();
            onSave();
          }}
        >
          <header>
            <div>
              <h2 id="latest-rule-editor-title">
                {draft.id ? "Modifica regola" : "Nuova regola"}
              </h2>
              <p>
                Ogni regola usa uno o più server, un preset e una sola
                destinazione Telegram.
              </p>
            </div>
            <Button
              type="button"
              variant="ghost"
              size="icon"
              title="Chiudi"
              aria-label="Chiudi"
              onClick={() => void requestClose()}
              disabled={saving}
            >
              <X size={18} aria-hidden="true" />
            </Button>
          </header>
          <label>
            Nome regola
            <input
              required
              value={draft.name}
              disabled={saving}
              onChange={(event) =>
                onChange({ ...draft, name: event.target.value })
              }
              placeholder="Film canale pubblico"
            />
          </label>
          <fieldset>
            <legend>Server Emby</legend>
            <div>
              {servers.map((server) => (
                <label key={server.id}>
                  <input
                    type="checkbox"
                    checked={draft.server_ids.includes(server.id)}
                    disabled={saving}
                    onChange={(event) =>
                      onChange({
                        ...draft,
                        server_ids: event.target.checked
                          ? [...draft.server_ids, server.id]
                          : draft.server_ids.filter((id) => id !== server.id),
                      })
                    }
                  />
                  {server.name}
                </label>
              ))}
            </div>
            {!draft.server_ids.length ? (
              <small>Seleziona almeno un server.</small>
            ) : null}
          </fieldset>
          <label>
            Preset
            <select
              required
              value={draft.preset_id}
              disabled={saving}
              onChange={(event) =>
                onChange({ ...draft, preset_id: event.target.value })
              }
            >
              <option value="">Seleziona preset...</option>
              {presets.map((preset) => (
                <option key={preset.id} value={preset.id}>
                  {preset.name}
                </option>
              ))}
            </select>
          </label>
          <div className="latest-rule-destination-field">
            <label>
              Destinazione Telegram
              <select
                required
                value={draft.telegram_config_id}
                disabled={saving}
                onChange={(event) =>
                  onChange({ ...draft, telegram_config_id: event.target.value })
                }
              >
                <option value="">Seleziona destinazione...</option>
                {telegramPresets.map((preset) => (
                  <option key={preset.id} value={preset.id}>
                    {preset.name}
                  </option>
                ))}
              </select>
            </label>
            <Button asChild type="button" variant="ghost" size="compact">
              <Link
                to="/configuration?focus=configuration-telegram#telegram"
                target="_blank"
                rel="noreferrer"
              >
                Gestisci Telegram
              </Link>
            </Button>
          </div>
          <footer>
            <Button
              type="button"
              variant="ghost"
              onClick={() => void requestClose()}
              disabled={saving}
            >
              Annulla
            </Button>
            <Button
              type="submit"
              variant="primary"
              disabled={saving || !draft.server_ids.length}
            >
              Salva regola
            </Button>
          </footer>
        </form>
      </DialogBackdrop>
      {confirmation.dialog}
    </>
  );
}

export { LatestRuleEditor };
