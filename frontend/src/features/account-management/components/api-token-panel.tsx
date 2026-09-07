import { ClipboardCopy, KeyRound, Plus, RefreshCw, Trash2, X } from "@/components/ui/icons";
import { useEffect, useRef, useState, type FormEvent } from "react";

import { Button } from "@/components/ui/button";
import { useConfirmationDialog } from "@/components/ui/use-confirmation-dialog";
import { apiTokenPermissionProfileLabels, apiTokenScopeLabels, formatAccountDate, formatApiTokenAction } from "@/features/account-management/account-presentation";
import type { ApiToken, ApiTokenPermissionProfile, ApiTokenPermissionProfileId, CreatedApiToken } from "@/features/account-management/types";
import { WriteAction } from "@/features/session/workspace-capabilities";
import {
  isOwnerBoundBrowserActionCancelled,
  useOwnerBoundBrowserAction,
} from "@/features/session/use-owner-bound-browser-action";
import { writeBrowserClipboard } from "@/lib/browser-download";

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
  actionPending?: boolean;
  revokingTokenId?: number;
  error?: string;
  onCreate: (input: { name: string; permissionProfile: ApiTokenPermissionProfileId; expiresInDays: number | null }) => Promise<CreatedApiToken>;
  onResetErrors?: () => void;
  onRevoke: (tokenId: number) => Promise<unknown>;
  onRotate: (tokenId: number) => Promise<CreatedApiToken>;
  onSecretPendingChange?: (pending: boolean) => void;
  rotatingTokenId?: number;
};

function ApiTokenPanel({
  actionPending = false,
  availablePermissionProfiles,
  creating,
  error,
  loading,
  onCreate,
  onResetErrors,
  onRevoke,
  onRotate,
  onSecretPendingChange,
  revokingTokenId,
  rotatingTokenId,
  tokens,
}: ApiTokenPanelProps) {
  const confirmation = useConfirmationDialog();
  const beginBrowserAction = useOwnerBoundBrowserAction();
  const profilesReady = availablePermissionProfiles.length > 0;
  const [name, setName] = useState("");
  const [permissionProfile, setPermissionProfile] = useState<ApiTokenPermissionProfileId>("read_only");
  const [expiresInDays, setExpiresInDays] = useState("90");
  const [created, setCreated] = useState<CreatedApiToken | null>(null);
  const [secretCopied, setSecretCopied] = useState(false);
  const [notice, setNotice] = useState("");
  const [localError, setLocalError] = useState("");
  const [localActionPending, setLocalActionPending] = useState(false);
  const operationInFlightRef = useRef(false);
  const secretInputRef = useRef<HTMLInputElement>(null);
  const operationsLocked =
    actionPending || localActionPending || created !== null;

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

  useEffect(() => {
    onSecretPendingChange?.(created !== null);
    return () => {
      if (created) onSecretPendingChange?.(false);
    };
  }, [created, onSecretPendingChange]);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (operationInFlightRef.current || operationsLocked) return;
    onResetErrors?.();
    setNotice("");
    setLocalError("");
    if (!name.trim() || !availablePermissionProfiles.some((profile) => profile.id === permissionProfile)) {
      setLocalError("Indica nome e profilo permessi.");
      return;
    }
    operationInFlightRef.current = true;
    setLocalActionPending(true);
    try {
      const payload = await onCreate({ name: name.trim(), permissionProfile, expiresInDays: expiresInDays ? Number(expiresInDays) : null });
      setSecretCopied(false);
      setCreated(payload);
      setName("");
      setPermissionProfile("read_only");
      setExpiresInDays("90");
    } catch (requestError) {
      setLocalError(requestError instanceof Error ? requestError.message : "Impossibile creare il token API.");
    } finally {
      operationInFlightRef.current = false;
      setLocalActionPending(false);
    }
  }

  async function copySecret(secret: string) {
    const action = beginBrowserAction();
    setNotice("");
    secretInputRef.current?.focus();
    secretInputRef.current?.select();
    try {
      await writeBrowserClipboard(secret, action);
      setSecretCopied(true);
      setNotice("Token copiato negli appunti.");
    } catch (error) {
      if (isOwnerBoundBrowserActionCancelled(error)) return;
      try {
        action.assertCurrent();
      } catch (ownerError) {
        if (isOwnerBoundBrowserActionCancelled(ownerError)) return;
        throw ownerError;
      }
      setNotice("Seleziona manualmente il token se il browser blocca la copia.");
    } finally {
      action.release();
    }
  }

  async function requestRevoke(token: ApiToken) {
    onResetErrors?.();
    setLocalError("");
    const confirmed = await confirmation.confirm({
      title: `Revocare ${token.name}?`,
      description: "Le applicazioni esterne che usano questo token non potranno più accedere a OctoHubs.",
      confirmLabel: "Revoca token",
      tone: "danger",
    });
    if (!confirmed) return;
    if (operationInFlightRef.current || operationsLocked) return;
    operationInFlightRef.current = true;
    setLocalActionPending(true);
    try {
      await onRevoke(token.id);
    } catch (requestError) {
      setLocalError(requestError instanceof Error ? requestError.message : "Impossibile revocare il token API.");
    } finally {
      operationInFlightRef.current = false;
      setLocalActionPending(false);
    }
  }

  async function requestRotate(token: ApiToken) {
    onResetErrors?.();
    setLocalError("");
    const confirmed = await confirmation.confirm({
      title: `Ruotare ${token.name}?`,
      description: "Il token attuale verrà revocato subito. Copia il nuovo valore prima di chiudere questa schermata.",
      confirmLabel: "Ruota token",
      tone: "danger",
    });
    if (!confirmed) return;
    if (operationInFlightRef.current || operationsLocked) return;
    operationInFlightRef.current = true;
    setLocalActionPending(true);
    try {
      const payload = await onRotate(token.id);
      setSecretCopied(false);
      setCreated(payload);
    } catch (requestError) {
      setLocalError(requestError instanceof Error ? requestError.message : "Impossibile ruotare il token API.");
    } finally {
      operationInFlightRef.current = false;
      setLocalActionPending(false);
    }
  }

  async function dismissCreatedSecret() {
    if (!secretCopied && !(await confirmation.confirm({
      title: "Token non ancora copiato",
      description: "Nascondere definitivamente questo token? Non potrà essere mostrato di nuovo.",
      confirmLabel: "Nascondi token",
      tone: "danger",
    }))) return;
    setCreated(null);
    setSecretCopied(false);
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
            <Button type="button" variant="ghost" size="icon" title="Nascondi token" aria-label="Nascondi token" onClick={() => void dismissCreatedSecret()}>
              <X size={15} aria-hidden="true" />
            </Button>
          </div>
        </div>
      ) : null}

      <WriteAction>
        <form className="api-token-form" onSubmit={(event) => void submit(event)}>
          <label>
            Nome token
            <input value={name} disabled={operationsLocked} placeholder="IA esterna, automazione, script..." onChange={(event) => setName(event.target.value)} />
          </label>
          <label>
            Scadenza
            <select value={expiresInDays} disabled={operationsLocked} onChange={(event) => setExpiresInDays(event.target.value)}>
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
                  <input type="radio" name="api-token-permission-profile" value={profile.id} checked={profile.id === permissionProfile} disabled={operationsLocked} onChange={() => setPermissionProfile(profile.id)} />
                  <span>
                    <strong>{apiTokenPermissionProfileLabels[profile.id]}</strong>
                    <small>{apiTokenPermissionProfileDescriptions[profile.id]}</small>
                  </span>
                </label>
              ))}
            </div>
          </fieldset>
          <footer>
            <Button type="submit" variant="secondary" size="compact" disabled={operationsLocked || !profilesReady}>
              <Plus size={15} aria-hidden="true" />{creating || localActionPending ? "Operazione in corso..." : "Crea token"}
            </Button>
          </footer>
        </form>
      </WriteAction>

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
            <WriteAction>
              <div className="api-token-actions">
                <Button type="button" variant="ghost" size="icon" title="Ruota token" aria-label={`Ruota ${token.name}`} disabled={operationsLocked || token.status !== "active" || rotatingTokenId === token.id} onClick={() => void requestRotate(token)}>
                  <RefreshCw size={16} aria-hidden="true" />
                </Button>
                <Button type="button" variant="ghost" size="icon" title="Revoca token" aria-label={`Revoca ${token.name}`} disabled={operationsLocked || !token.is_active || revokingTokenId === token.id} onClick={() => void requestRevoke(token)}>
                  <Trash2 size={16} aria-hidden="true" />
                </Button>
              </div>
            </WriteAction>
          </article>
        )) : null}
      </div>
      {confirmation.dialog}
    </section>
  );
}

export { ApiTokenPanel };
