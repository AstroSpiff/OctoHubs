import { TraktDeviceFlow } from "@/features/configuration/components/trakt-device-flow";
import { SavedCredentialControl } from "@/features/configuration/components/saved-credential-control";
import type { ConfigurationServices, ServiceSettingsInput } from "@/features/configuration/types";

function ServiceCatalogSettings({
  trakt,
  justwatch,
  snapshot,
  saving,
  onTraktChange,
  onJustWatchChange,
  onNotice,
  onRefreshSettings,
}: {
  trakt: ServiceSettingsInput["trakt"];
  justwatch: ServiceSettingsInput["justwatch"];
  snapshot: ConfigurationServices;
  saving: boolean;
  onTraktChange: (next: ServiceSettingsInput["trakt"]) => void;
  onJustWatchChange: (next: ServiceSettingsInput["justwatch"]) => void;
  onNotice: (message: string) => void;
  onRefreshSettings: () => void;
}) {
  return <section id="configuration-catalogs" className="service-form-grid service-form-grid--integrations" tabIndex={-1}>
    <header><h3>Cataloghi</h3><p>Trakt usa il device flow per associare l'account e JustWatch controlla il catalogo locale.</p></header>
    <label className="configuration-switch"><input type="checkbox" checked={trakt.enabled} onChange={(event) => onTraktChange({ ...trakt, enabled: event.target.checked })} />Abilita Trakt</label>
    <label>Client ID Trakt<input type="text" value={trakt.client_id} onChange={(event) => onTraktChange({ ...trakt, client_id: event.target.value })} /></label>
    <label>Client Secret Trakt<input type="password" disabled={trakt.clear_client_secret} placeholder={snapshot.trakt.client_secret_configured ? "Lascia vuoto per conservarlo" : "Client Secret"} value={trakt.client_secret || ""} onChange={(event) => onTraktChange({ ...trakt, client_secret: event.target.value, clear_client_secret: false })} /><SavedCredentialControl configured={snapshot.trakt.client_secret_configured} pendingRemoval={Boolean(trakt.clear_client_secret)} label="Rimuovi Client Secret salvato" onPendingRemovalChange={(clear_client_secret) => onTraktChange({ ...trakt, clear_client_secret, client_secret: "" })} /></label>
    <details className="service-catalog-advanced">
      <summary>Token Trakt manuale</summary>
      <label>
        Token di accesso
        <input
          type="password"
          autoComplete="new-password"
          disabled={saving}
          placeholder={snapshot.trakt.access_token_configured ? "Lascia vuoto per conservarlo" : "Token OAuth Trakt"}
          value={trakt.access_token || ""}
          onChange={(event) => onTraktChange({ ...trakt, access_token: event.target.value })}
        />
      </label>
      <p>Usalo soltanto se vuoi configurare un token OAuth esistente invece del device flow.</p>
    </details>
    <div className="trakt-device-cell"><TraktDeviceFlow clientId={trakt.client_id} clientSecret={trakt.client_secret || ""} connected={snapshot.trakt.access_token_configured} expiresAt={snapshot.trakt.expires_at} disabled={saving || Boolean(trakt.clear_client_secret)} onChanged={(message) => { onNotice(message); onRefreshSettings(); }} /></div>
    <label className="configuration-switch"><input type="checkbox" checked={justwatch.enabled} onChange={(event) => onJustWatchChange({ ...justwatch, enabled: event.target.checked })} />Abilita JustWatch</label>
    <label>Locale JustWatch<select value={justwatch.locale} onChange={(event) => onJustWatchChange({ ...justwatch, locale: event.target.value })}><option value="it_IT">Italia</option><option value="en_US">USA</option><option value="en_GB">UK</option><option value="fr_FR">Francia</option><option value="de_DE">Germania</option><option value="es_ES">Spagna</option></select></label>
  </section>;
}

export { ServiceCatalogSettings };
