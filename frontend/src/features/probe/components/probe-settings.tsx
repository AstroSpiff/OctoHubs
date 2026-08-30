import { RotateCcw, Save } from "@/components/ui/icons";
import { useEffect } from "react";

import { Button } from "@/components/ui/button";
import { probeConfigDefaults } from "@/features/probe/presentation";
import { ProbeServerTabs } from "@/features/probe/components/probe-server-tabs";
import { WriteAction } from "@/features/session/workspace-capabilities";
import type { ProbeConfig, ProbeScope, ProbeServer } from "@/features/probe/types";
import { boundedWholeNumberInput } from "@/lib/numeric-input";
import { useSynchronizedDraft } from "@/lib/use-synchronized-draft";

function ProbeSettings({
  scope,
  serverName,
  config,
  disabled,
  saving,
  error,
  saved,
  configServers,
  configServerId,
  onConfigServerChange,
  onSave,
  onDirtyChange,
}: {
  scope: ProbeScope;
  serverName?: string;
  config?: ProbeConfig;
  disabled: boolean;
  saving: boolean;
  error?: string;
  saved: boolean;
  configServers?: ProbeServer[];
  configServerId?: string;
  onConfigServerChange?: (serverId: string) => boolean | void | Promise<boolean | void>;
  onSave: (config: ProbeConfig) => Promise<ProbeConfig>;
  onDirtyChange?: (dirty: boolean) => void;
}) {
  const savedConfig = config || probeConfigDefaults;
  const { accept, dirty, discard, draft, setDraft } = useSynchronizedDraft(
    savedConfig,
    copyProbeConfig,
  );

  useEffect(() => {
    onDirtyChange?.(dirty);
    return () => onDirtyChange?.(false);
  }, [dirty, onDirtyChange]);

  function update<K extends keyof ProbeConfig>(key: K, value: ProbeConfig[K]) {
    setDraft((current) => (current ? { ...current, [key]: value } : current));
  }

  async function save() {
    if (!draft) return;
    try {
      accept(await onSave(draft), draft);
    } catch {
      // The mutation error is shown by the parent query state.
    }
  }

  if (!draft) return null;

  return (
    <section className="probe-settings" aria-labelledby="probe-settings-title">
      <header>
        <div>
          <h3 id="probe-settings-title" className="contextual-heading">
            Configurazione {scope === "libraries" ? "librerie" : "ultimi aggiunti"}
          </h3>
          <p>
            {disabled
              ? "Seleziona un server specifico per modificare i parametri."
              : `Parametri salvati per ${serverName || "il server selezionato"}.`}
          </p>
          {configServers && configServerId && onConfigServerChange ? (
            <div className="probe-settings-server-target">
              <span>Server da configurare</span>
              <ProbeServerTabs
                servers={configServers}
                value={configServerId}
                onChange={onConfigServerChange}
              />
            </div>
          ) : null}
        </div>
      </header>
      {error ? <p className="probe-settings-feedback is-error" role="alert">{error}</p> : null}
      {saved && !dirty ? (
        <p className="probe-settings-feedback is-success" role="status">
          Configurazione Probe salvata.
        </p>
      ) : null}
      <WriteAction>
        <div className="probe-settings-groups">
        <SettingsGroup
          title="Comune"
          description="Si applica sia alle librerie sia agli ultimi aggiunti."
        >
          <label>
            <span>File da analizzare</span>
            <select
              value={draft.media_policy}
              disabled={disabled || saving}
              onChange={(event) =>
                update(
                  "media_policy",
                  event.target.value === "missing_media_info"
                    ? "missing_media_info"
                    : "strm_only",
                )
              }
            >
              <option value="strm_only">Solo file STRM</option>
              <option value="missing_media_info">File video senza MediaInfo</option>
            </select>
          </label>
          <label>
            <span>Slot simultanei</span>
            <select
              value={draft.probe_parallelism}
              disabled={disabled || saving}
              onChange={(event) => update("probe_parallelism", Number(event.target.value))}
            >
              {[1, 2, 3, 4, 5, 6, 7, 8].map((value) => (
                <option key={value} value={value}>{value}x</option>
              ))}
            </select>
          </label>
        </SettingsGroup>
        {scope === "recent" ? (
          <>
            <SettingsGroup
              title="Finestra scorrevole"
              description="Definisce quando fermare la ricerca dopo aver incontrato elementi completi."
            >
              <label>
                <span>Dimensione finestra</span>
                <input
                  type="number"
                  min="100"
                  max="2000"
                  step="100"
                  value={draft.window_size}
                  disabled={disabled || saving}
                  onChange={(event) => update("window_size", boundedWholeNumberInput(event.target.value, 100, 2000))}
                />
              </label>
              <label>
                <span>Soglia completamento (%)</span>
                <input
                  type="number"
                  min="50"
                  max="100"
                  step="5"
                  value={Math.round(draft.window_threshold * 100)}
                  disabled={disabled || saving}
                  onChange={(event) => update("window_threshold", boundedWholeNumberInput(event.target.value, 50, 100) / 100)}
                />
              </label>
            </SettingsGroup>
            <SettingsGroup
              title="Intervallo di ricerca"
              description="Limita l'intervallo e il numero di elementi esaminati dagli ultimi aggiunti."
            >
              <label>
                <span>Margine sicurezza (giorni)</span>
                <input type="number" min="1" max="30" value={draft.safety_margin_days} disabled={disabled || saving} onChange={(event) => update("safety_margin_days", boundedWholeNumberInput(event.target.value, 1, 30))} />
              </label>
              <label>
                <span>Massimo giorni</span>
                <input type="number" min="7" max="365" value={draft.max_days} disabled={disabled || saving} onChange={(event) => update("max_days", boundedWholeNumberInput(event.target.value, 7, 365))} />
              </label>
              <label>
                <span>Massimo elementi</span>
                <input type="number" min="500" max="10000" step="500" value={draft.max_items} disabled={disabled || saving} onChange={(event) => update("max_items", boundedWholeNumberInput(event.target.value, 500, 10000))} />
              </label>
            </SettingsGroup>
          </>
        ) : null}
        </div>
      {dirty ? (
        <div className="configuration-draft-state" role="status">
          <span>Modifiche non salvate</span>
          <Button type="button" variant="ghost" size="compact" onClick={discard} disabled={saving}>
            Ripristina valori salvati
          </Button>
        </div>
      ) : null}
      <footer>
        <Button type="button" variant="ghost" size="compact" onClick={() => setDraft(probeConfigDefaults)} disabled={disabled || saving}>
          <RotateCcw size={14} aria-hidden="true" />
          Ripristina
        </Button>
        <Button type="button" requiresWriteAccess variant="primary" size="compact" onClick={() => void save()} disabled={disabled || saving}>
          <Save size={14} aria-hidden="true" />
          {saving ? "Salvataggio..." : "Salva"}
        </Button>
      </footer>
      </WriteAction>
    </section>
  );
}

function copyProbeConfig(value: ProbeConfig): ProbeConfig {
  return { ...value };
}

function SettingsGroup({ title, description, children }: { title: string; description: string; children: React.ReactNode }) {
  return (
    <section className="probe-settings-group">
      <header><h3>{title}</h3><p>{description}</p></header>
      <div>{children}</div>
    </section>
  );
}

export { ProbeSettings };
