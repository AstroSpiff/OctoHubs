import { ClipboardCopy, KeyRound, Plus, RefreshCw, Trash2, X } from "@/components/ui/icons";
import { useEffect, useRef, useState, type FormEvent } from "react";

import { Button } from "@/components/ui/button";
import { useConfirmationDialog } from "@/components/ui/use-confirmation-dialog";
import { apiTokenPermissionProfileLabels, apiTokenScopeLabels, formatAccountDate, formatApiTokenAction } from "@/features/account-management/account-presentation";
import type { ApiToken, ApiTokenPermissionProfile, ApiTokenPermissionProfileId, CreatedApiToken } from "@/features/account-management/types";

const apiTokenPermissionProfileDescriptions: Record<ApiTokenPermissionProfileId, string> = {
  read_only: "Consulta dati e stato senza modificare nulla.",
  operator: "Gestisce le funzioni operative, senza intervenire su account e token.",
  administrator: "Accesso completo all'istanza. Disponibile solo agli amministratori.",
};

type ApiTokenPanelProps = {
  availablePermissionProfiles: ApiTokenPermissionProfile[];
  tokens: ApiToken[];
  loading: boolean;
  creating: boolean;
  revokingTokenId?: number;
  error?: string;
  onCreate: (input: { name: string; permissionProfile: ApiTokenPermissionProfileId; expiresInDays: number | null }) => Promise<CreatedApiToken>;
  onRevoke: (tokenId: number) => Promise<unknown>;
  onRotate: (tokenId: number) => Promise<CreatedApiToken>;
  rotatingTokenId?: number;
};

function ApiTokenPanel({
  availablePermissionProfiles,
  creating,
  error,
  loading,
  onCreate,
  onRevoke,
  onRotate,
  revokingTokenId,
  rotatingTokenId,
  tokens,
}: ApiTokenPanelProps) {
  const confirmation = useConfirmationDialog();
  const profilesReady = availablePermissionProfiles.length > 0;
  const [name, setName] = useState("");
  const [permissionProfile, setPermissionProfile] = useState<ApiTokenPermissionProfileId>("read_only");
  const [expiresInDays, setExpiresInDays] = useState("90");
  const [created, setCreated] = useState<CreatedApiToken | null>(null);
  const [notice, setNotice] = useState("");
  const [localError, setLocalError] = useState("");
  const secretInputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (!availablePermissionProfiles.some((profile) => profile.id === permissionProfile)) {
      setPermissionProfile(availablePermissionProfiles[0]?.id || "read_only");
    }
  }, [availablePermissionProfiles, permissionProfile]);

  useEffect(() => {
    if (!created) return;
    secretInputRef.current?.focus();
    secretInputRef.current?.select();
  }, [created]);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setNotice("");
    setLocalError("");
    setCreated(null);
    if (!name.trim() || !availablePermissionProfiles.some((profile) => profile.id === permissionProfile)) {
      setLocalError("Indica nome e profilo permessi.");
      return;
    }
    try {
      const payload = await onCreate({ name: name.trim(), permissionProfile, expiresInDays: expiresInDays ? Number(expiresInDays) : null });
      setCreated(payload);
      setName("");
      setPermissionProfile("read_only");
      setExpiresInDays("90");
    } catch (requestError) {
      setLocalError(requestError instanceof Error ? requestError.message : "Impossibile creare il token API.");
    }
  }

  async function copySecret(secret: string) {
    setNotice("");
    secretInputRef.current?.focus();
    secretInputRef.current?.select();
    try {
      if (!navigator.clipboard?.writeText) throw new Error("Clipboard non disponibile");
      await navigator.clipboard.writeText(secret);
      setNotice("Token copiato negli appunti.");
    } catch {
      setNotice("Seleziona manualmente il token se il browser blocca la copia.");
    }
  }

  async function requestRevoke(token: ApiToken) {
    const confirmed = await confirmation.confirm({
      title: `Revocare ${token.name}?`,
      description: "Le applicazioni esterne che usano questo token non potranno più accedere a OctoHubs.",
      confirmLabel: "Revoca token",
      tone: "danger",
    });
    if (!confirmed) return;
    await onRevoke(token.id);
  }

  async function requestRotate(token: ApiToken) {
    const confirmed = await confirmation.confirm({
      title: `Ruotare ${token.name}?`,
      description: "Il token attuale verrà revocato subito. Copia il nuovo valore prima di chiudere questa schermata.",
      confirmLabel: "Ruota token",
      tone: "danger",
    });
    if (!confirmed) return;
    setCreated(await onRotate(token.id));
  }

  return (
    <section className="api-token-panel" aria-labelledby="api-token-title">
      <header>
        <div>
          <h3 id="api-token-title" className="contextual-heading" title="Accesso esterno">API token</h3>
          <p>Permetti ad app esterne e agenti IA di usare gli stessi endpoint JSON di OctoHubs con permessi espliciti.</p>
        </div>
        <KeyRound size={18} aria-hidden="true" />
      </header>

      {error || localError ? <div className="inline-alert inline-alert--error" role="alert">{localError || error}</div> : null}
      {notice ? <p className="account-form-feedback is-success" role="status">{notice}</p> : null}
      {created ? (
        <div className="api-token-secret" role="status">
          <div>
            <strong>Token creato</strong>
            <small>Copialo ora: non verra piu mostrato.</small>
          </div>
          <div className="api-token-secret-value">
            <input ref={secretInputRef} aria-label="Token appena creato" value={created.secret} readOnly onFocus={(event) => event.currentTarget.select()} />
            <Button type="button" variant="secondary" size="compact" title="Copia token" onClick={() => void copySecret(created.secret)}>
              <ClipboardCopy size={15} aria-hidden="true" />Copia
            </Button>
            <Button type="button" variant="ghost" size="icon" title="Nascondi token" aria-label="Nascondi token" onClick={() => setCreated(null)}>
              <X size={15} aria-hidden="true" />
            </Button>
          </div>
        </div>
      ) : null}

      <form className="api-token-form" onSubmit={(event) => void submit(event)}>
        <label>
          Nome token
          <input value={name} disabled={creating} placeholder="IA esterna, automazione, script..." onChange={(event) => setName(event.target.value)} />
        </label>
        <label>
          Scadenza
          <select value={expiresInDays} disabled={creating} onChange={(event) => setExpiresInDays(event.target.value)}>
            <option value="30">30 giorni</option>
            <option value="90">90 giorni</option>
            <option value="365">1 anno</option>
            <option value="">Senza scadenza</option>
          </select>
        </label>
        <fieldset className="api-token-permission-profiles">
          <legend>Profilo permessi</legend>
          <div role="radiogroup" aria-label="Profilo permessi API token">
            {!profilesReady ? <span className="api-token-profile-loading">Caricamento profili...</span> : null}
            {availablePermissionProfiles.map((profile) => (
              <label key={profile.id} className={profile.id === permissionProfile ? "is-selected" : ""}>
                <input type="radio" name="api-token-permission-profile" value={profile.id} checked={profile.id === permissionProfile} disabled={creating} onChange={() => setPermissionProfile(profile.id)} />
                <span>
                  <strong>{apiTokenPermissionProfileLabels[profile.id]}</strong>
                  <small>{apiTokenPermissionProfileDescriptions[profile.id]}</small>
                </span>
              </label>
            ))}
          </div>
        </fieldset>
        <footer>
          <Button type="submit" variant="secondary" size="compact" disabled={creating || !profilesReady}>
            <Plus size={15} aria-hidden="true" />{creating ? "Creazione..." : "Crea token"}
          </Button>
        </footer>
      </form>

      <div className="api-token-list" aria-live="polite">
        {loading ? <div className="loading-state">Caricamento token API...</div> : null}
        {!loading && !tokens.length ? <p className="account-empty">Nessun token API creato.</p> : null}
        {!loading ? tokens.map((token) => (
          <article key={token.id} className={`api-token-row${token.status === "active" ? "" : " is-inactive"}`}>
            <div>
              <strong>{token.name}</strong>
              <small>{token.prefix}... · creato {formatAccountDate(token.created_at)} · {token.status === "expired" ? `scaduto ${formatAccountDate(token.expires_at)}` : token.status === "revoked" ? "revocato" : token.expires_at ? `scade ${formatAccountDate(token.expires_at)}` : "senza scadenza"} · ultimo uso {formatAccountDate(token.last_used_at)}</small>
              <small>{formatApiTokenAction(token.last_action)}</small>
            </div>
            <div className="api-token-permission-summary">
              <span className="api-token-profile">{token.permission_profile ? apiTokenPermissionProfileLabels[token.permission_profile] : "Permessi specifici"}</span>
              <details className="api-token-scopes">
                <summary>Dettaglio permessi</summary>
                <div>{token.scopes.map((scope) => <span key={scope}>{apiTokenScopeLabels[scope]}</span>)}</div>
              </details>
            </div>
            <div className="api-token-actions">
              <Button type="button" variant="ghost" size="icon" title="Ruota token" aria-label={`Ruota ${token.name}`} disabled={token.status !== "active" || rotatingTokenId === token.id} onClick={() => void requestRotate(token)}>
                <RefreshCw size={16} aria-hidden="true" />
              </Button>
              <Button type="button" variant="ghost" size="icon" title="Revoca token" aria-label={`Revoca ${token.name}`} disabled={!token.is_active || revokingTokenId === token.id} onClick={() => void requestRevoke(token)}>
                <Trash2 size={16} aria-hidden="true" />
              </Button>
            </div>
          </article>
        )) : null}
      </div>
      {confirmation.dialog}
    </section>
  );
}

export { ApiTokenPanel };
