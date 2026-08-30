import { Check, Database, RefreshCw, Save } from "@/components/ui/icons";
import { useEffect, useState } from "react";
import type { FormEvent } from "react";

import { Button } from "@/components/ui/button";
import { WriteAction } from "@/features/session/workspace-capabilities";
import { WorkspaceHeading } from "@/components/ui/workspace-heading";
import { DatabaseSettingsSection } from "@/features/configuration/components/database-settings-section";
import { QbittorrentConnectionCard } from "@/features/configuration/components/qbittorrent-connection-card";
import { ServiceCatalogSettings } from "@/features/configuration/components/service-catalog-settings";
import { ServiceConnectionCard } from "@/features/configuration/components/service-connection-card";
import { ServiceConnectionChecks } from "@/features/configuration/components/service-connection-checks";
import { ServiceMetadataSettings } from "@/features/configuration/components/service-metadata-settings";
import { serviceInputFromSnapshot, splitKeys } from "@/features/configuration/service-settings-model";
import type { ConfigurationServices, ConnectionCheckPayload, ServiceSettingsInput } from "@/features/configuration/types";
import { useSynchronizedDraft } from "@/lib/use-synchronized-draft";

type ServiceSettingsPanelProps = {
  services?: ConfigurationServices;
  saving: boolean;
  savedMessage: string;
  onSave: (value: ServiceSettingsInput) => Promise<ConfigurationServices>;
  onTestConnections: () => Promise<ConnectionCheckPayload>;
  onRefreshSettings: () => void;
  onNotice: (message: string) => void;
  onDirtyChange?: (dirty: boolean) => void;
};

function ServiceSettingsPanel({
  services,
  saving,
  savedMessage,
  onSave,
  onTestConnections,
  onRefreshSettings,
  onNotice,
  onDirtyChange,
}: ServiceSettingsPanelProps) {
  const { accept, dirty, discard, draft, setDraft } = useSynchronizedDraft(services, serviceInputFromSnapshot);
  const [mdblistKeys, setMdblistKeys] = useState("");
  const [omdbKeys, setOmdbKeys] = useState("");
  const [checks, setChecks] = useState<ConnectionCheckPayload["statuses"] | null>(null);
  const [checking, setChecking] = useState(false);
  const [checkError, setCheckError] = useState("");
  const [saveError, setSaveError] = useState("");

  useEffect(() => {
    onDirtyChange?.(dirty);
    return () => onDirtyChange?.(false);
  }, [dirty, onDirtyChange]);

  if (!draft || !services) return <div className="loading-state">Caricamento configurazione servizi...</div>;
  const currentDraft = draft;

  function updateConnections(next: ServiceSettingsInput["connections"]) {
    setDraft((current) => current ? { ...current, connections: next } : current);
  }

  function updateConnection(
    name: "jellyseerr" | "prowlarr" | "jackett",
    value: ServiceSettingsInput["connections"]["jellyseerr"],
  ) {
    updateConnections({ ...currentDraft.connections, [name]: value });
  }

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    void save({
      ...currentDraft,
      connections: {
        ...currentDraft.connections,
        mdblist: addSubmittedKeyList(currentDraft.connections.mdblist, mdblistKeys),
        omdb: addSubmittedKeyList(currentDraft.connections.omdb, omdbKeys),
      },
    });
  }

  async function save(value: ServiceSettingsInput) {
    setSaveError("");
    try {
      accept(await onSave(value), currentDraft);
      setMdblistKeys("");
      setOmdbKeys("");
    } catch (error) {
      setSaveError(error instanceof Error ? error.message : "Impossibile salvare la configurazione servizi.");
    }
  }

  async function runCheck() {
    setChecking(true);
    setCheckError("");
    try {
      setChecks((await onTestConnections()).statuses);
    } catch (error) {
      setCheckError(error instanceof Error ? error.message : "Verifica connessioni non riuscita");
    } finally {
      setChecking(false);
    }
  }

  return <section className="configuration-panel" aria-labelledby="configuration-services-title">
    <WorkspaceHeading level="section" context="Integrazioni" leading={<Database size={18} aria-hidden="true" />} titleId="configuration-services-title" title="Configurazione servizi" description="Le credenziali esistenti restano protette: inseriscile solo per sostituirle." />
    {savedMessage ? <div className="inline-alert inline-alert--success" role="status"><Check size={17} aria-hidden="true" />{savedMessage}</div> : null}
    {saveError ? <div className="inline-alert inline-alert--error" role="alert">{saveError}</div> : null}
    {checkError ? <div className="inline-alert inline-alert--error" role="alert">{checkError}</div> : null}
    <WriteAction>
      {dirty ? <div className="configuration-draft-state" role="status"><span>Modifiche non salvate</span><Button type="button" variant="ghost" size="compact" onClick={() => { discard(); setMdblistKeys(""); setOmdbKeys(""); }} disabled={saving}>Ripristina valori salvati</Button></div> : null}
      <form className="service-settings-form" onSubmit={submit}>
      <fieldset className="configuration-editable-fields" disabled={saving}>
      <section id="configuration-connections" tabIndex={-1}><header><h3>Servizi richieste, ricerca e download</h3><p>Jellyseerr, almeno un indexer e qBittorrent completano il percorso dalla richiesta al download.</p></header><div className="service-connection-grid"><ServiceConnectionCard title="Jellyseerr" description="Gestione e stato delle richieste." value={currentDraft.connections.jellyseerr} configured={services.connections.jellyseerr.api_key_configured} onChange={(value) => updateConnection("jellyseerr", value)} /><ServiceConnectionCard title="Prowlarr" description="Indexer API principale." value={currentDraft.connections.prowlarr} configured={services.connections.prowlarr.api_key_configured} onChange={(value) => updateConnection("prowlarr", value)} /><ServiceConnectionCard title="Jackett" description="Indexer API alternativo." value={currentDraft.connections.jackett} configured={services.connections.jackett.api_key_configured} onChange={(value) => updateConnection("jackett", value)} /><QbittorrentConnectionCard value={currentDraft.connections.qbittorrent} snapshot={services.connections.qbittorrent} onChange={(value) => updateConnections({ ...currentDraft.connections, qbittorrent: value })} /></div></section>
      <ServiceMetadataSettings connections={currentDraft.connections} snapshot={services.connections} mdblistKeys={mdblistKeys} omdbKeys={omdbKeys} onChange={updateConnections} onMdblistKeysChange={setMdblistKeys} onOmdbKeysChange={setOmdbKeys} />
      <ServiceCatalogSettings trakt={currentDraft.trakt} justwatch={currentDraft.justwatch} snapshot={services} saving={saving} onTraktChange={(trakt) => setDraft((current) => current ? { ...current, trakt } : current)} onJustWatchChange={(justwatch) => setDraft((current) => current ? { ...current, justwatch } : current)} onNotice={onNotice} onRefreshSettings={onRefreshSettings} />
      <DatabaseSettingsSection value={currentDraft.database} snapshot={services.database} onChange={(database) => setDraft((current) => current ? { ...current, database } : current)} />
      </fieldset>
      <footer className="configuration-panel-actions"><Button type="button" variant="secondary" size="compact" onClick={() => void runCheck()} disabled={checking || saving}><RefreshCw size={16} className={checking ? "animate-spin" : ""} aria-hidden="true" />{checking ? "Verifica..." : "Verifica connessioni"}</Button><Button type="submit" variant="primary" size="compact" disabled={saving || !dirty}>{saving ? "Salvataggio..." : <><Save size={16} aria-hidden="true" />Salva configurazione</>}</Button></footer>
      </form>
    </WriteAction>
    {checks ? <ServiceConnectionChecks statuses={checks} /> : null}
  </section>;
}

function addSubmittedKeyList<T extends { api_keys?: string[]; clear_api_keys?: boolean }>(value: T, rawKeys: string): T {
  if (!rawKeys.trim() || value.clear_api_keys) return value;
  return { ...value, api_keys: splitKeys(rawKeys) };
}

export { ServiceSettingsPanel };
