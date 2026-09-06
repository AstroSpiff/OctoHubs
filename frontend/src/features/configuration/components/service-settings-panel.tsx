import { Check, Database, RefreshCw, Save } from "@/components/ui/icons";
import { useEffect, useRef, useState } from "react";
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
  const [checks, setChecks] = useState<{ revision: number; services: ConfigurationServices; statuses: ConnectionCheckPayload["statuses"] } | null>(null);
  const [checking, setChecking] = useState(false);
  const [checkError, setCheckError] = useState<{ message: string; revision: number; services: ConfigurationServices } | null>(null);
  const [saveError, setSaveError] = useState("");
  const [traktDeviceBusy, setTraktDeviceBusy] = useState(false);
  const draftRevisionRef = useRef(0);
  const effectiveDirty = dirty || Boolean(mdblistKeys.trim()) || Boolean(omdbKeys.trim());
  const visibleChecks = !effectiveDirty && checks?.revision === draftRevisionRef.current && checks.services === services
    ? checks.statuses
    : null;
  const visibleCheckError = !effectiveDirty && checkError?.revision === draftRevisionRef.current && checkError.services === services
    ? checkError.message
    : "";

  useEffect(() => {
    onDirtyChange?.(effectiveDirty);
    return () => onDirtyChange?.(false);
  }, [effectiveDirty, onDirtyChange]);

  if (!draft || !services) return <div className="loading-state">Caricamento configurazione servizi...</div>;
  const currentDraft = draft;
  const currentServices = services;

  function updateConnections(next: ServiceSettingsInput["connections"]) {
    invalidateConnectionChecks();
    setDraft((current) => current ? { ...current, connections: next } : current);
  }

  function invalidateConnectionChecks() {
    draftRevisionRef.current += 1;
  }

  function updateConnection(
    name: "jellyseerr" | "prowlarr" | "jackett",
    value: ServiceSettingsInput["connections"]["jellyseerr"],
  ) {
    updateConnections({ ...currentDraft.connections, [name]: value });
  }

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (traktDeviceBusy) return;
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
      invalidateConnectionChecks();
      setMdblistKeys("");
      setOmdbKeys("");
    } catch (error) {
      setSaveError(error instanceof Error ? error.message : "Impossibile salvare la configurazione servizi.");
    }
  }

  async function runCheck() {
    if (effectiveDirty) return;
    const checkedRevision = draftRevisionRef.current;
    const checkedServices = currentServices;
    setChecking(true);
    setCheckError(null);
    try {
      setChecks({
        revision: checkedRevision,
        services: checkedServices,
        statuses: (await onTestConnections()).statuses,
      });
    } catch (error) {
      setCheckError({
        message: error instanceof Error ? error.message : "Verifica connessioni non riuscita",
        revision: checkedRevision,
        services: checkedServices,
      });
    } finally {
      setChecking(false);
    }
  }

  return <section className="configuration-panel" aria-labelledby="configuration-services-title">
    <WorkspaceHeading level="section" context="Integrazioni" leading={<Database size={18} aria-hidden="true" />} titleId="configuration-services-title" title="Configurazione servizi" description="Le credenziali esistenti restano protette: inseriscile solo per sostituirle." />
    {savedMessage ? <div className="inline-alert inline-alert--success" role="status"><Check size={17} aria-hidden="true" />{savedMessage}</div> : null}
    {saveError ? <div className="inline-alert inline-alert--error" role="alert">{saveError}</div> : null}
    {visibleCheckError ? <div className="inline-alert inline-alert--error" role="alert">{visibleCheckError}</div> : null}
    <WriteAction>
      {effectiveDirty ? <div className="configuration-draft-state" role="status"><span>Modifiche non salvate</span><Button type="button" variant="ghost" size="compact" onClick={() => { invalidateConnectionChecks(); discard(); setMdblistKeys(""); setOmdbKeys(""); }} disabled={saving}>Ripristina valori salvati</Button></div> : null}
      <form className="service-settings-form" onSubmit={submit}>
      <fieldset className="configuration-editable-fields" disabled={saving}>
      <section id="configuration-connections" tabIndex={-1}><header><h3>Servizi richieste, ricerca e download</h3><p>Jellyseerr, almeno un indexer e qBittorrent completano il percorso dalla richiesta al download.</p></header><div className="service-connection-grid"><ServiceConnectionCard title="Jellyseerr" description="Gestione e stato delle richieste." value={currentDraft.connections.jellyseerr} configured={services.connections.jellyseerr.api_key_configured} onChange={(value) => updateConnection("jellyseerr", value)} /><ServiceConnectionCard title="Prowlarr" description="Indexer API principale." value={currentDraft.connections.prowlarr} configured={services.connections.prowlarr.api_key_configured} onChange={(value) => updateConnection("prowlarr", value)} /><ServiceConnectionCard title="Jackett" description="Indexer API alternativo." value={currentDraft.connections.jackett} configured={services.connections.jackett.api_key_configured} onChange={(value) => updateConnection("jackett", value)} /><QbittorrentConnectionCard value={currentDraft.connections.qbittorrent} snapshot={services.connections.qbittorrent} onChange={(value) => updateConnections({ ...currentDraft.connections, qbittorrent: value })} /></div></section>
      <ServiceMetadataSettings connections={currentDraft.connections} snapshot={services.connections} mdblistKeys={mdblistKeys} omdbKeys={omdbKeys} onChange={updateConnections} onMdblistKeysChange={(value) => { invalidateConnectionChecks(); setMdblistKeys(value); }} onOmdbKeysChange={(value) => { invalidateConnectionChecks(); setOmdbKeys(value); }} />
      <ServiceCatalogSettings trakt={currentDraft.trakt} justwatch={currentDraft.justwatch} snapshot={services} saving={saving} traktDeviceBusy={traktDeviceBusy} onTraktChange={(trakt) => { invalidateConnectionChecks(); setDraft((current) => current ? { ...current, trakt } : current); }} onJustWatchChange={(justwatch) => { invalidateConnectionChecks(); setDraft((current) => current ? { ...current, justwatch } : current); }} onNotice={onNotice} onRefreshSettings={onRefreshSettings} onTraktBusyChange={setTraktDeviceBusy} />
      </fieldset>
      <footer className="configuration-panel-actions"><Button type="button" variant="secondary" size="compact" title={effectiveDirty ? "Salva o ripristina le modifiche prima di verificare le connessioni" : "Verifica le connessioni della configurazione salvata"} onClick={() => void runCheck()} disabled={checking || saving || effectiveDirty || traktDeviceBusy}><RefreshCw size={16} className={checking ? "animate-spin" : ""} aria-hidden="true" />{checking ? "Verifica..." : "Verifica connessioni"}</Button><Button type="submit" variant="primary" size="compact" disabled={saving || traktDeviceBusy || !effectiveDirty}>{saving ? "Salvataggio..." : <><Save size={16} aria-hidden="true" />Salva configurazione</>}</Button></footer>
      </form>
    </WriteAction>
    <DatabaseSettingsSection snapshot={services.database} />
    {visibleChecks ? <ServiceConnectionChecks statuses={visibleChecks} /> : null}
  </section>;
}

function addSubmittedKeyList<T extends { api_keys?: string[]; clear_api_keys?: boolean }>(value: T, rawKeys: string): T {
  if (!rawKeys.trim() || value.clear_api_keys) return value;
  return { ...value, api_keys: splitKeys(rawKeys) };
}

export { ServiceSettingsPanel };
