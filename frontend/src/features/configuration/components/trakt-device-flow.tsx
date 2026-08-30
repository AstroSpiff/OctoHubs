import { ExternalLink, RefreshCw, Unplug, X } from "@/components/ui/icons";
import { useEffect, useRef, useState } from "react";

import { Button } from "@/components/ui/button";
import { clearTraktDeviceFlow, pollTraktDeviceFlow, startTraktDeviceFlow } from "@/features/configuration/api";
import { formatConfigurationMoment } from "@/features/configuration/automation-presentation";
import {
  createTraktDeviceAttempt,
  traktDeviceAttemptExpired,
} from "@/features/configuration/trakt-device-attempt";
import type { TraktDeviceAttempt } from "@/features/configuration/trakt-device-attempt";

function TraktDeviceFlow({ clientId, clientSecret, connected, expiresAt, disabled, onChanged }: { clientId: string; clientSecret: string; connected: boolean; expiresAt: string; disabled: boolean; onChanged: (message: string) => void }) {
  const [attempt, setAttempt] = useState<TraktDeviceAttempt | null>(null);
  const [status, setStatus] = useState("");
  const [busy, setBusy] = useState(false);
  const timer = useRef<number | null>(null);

  function clearPolling() {
    if (timer.current) window.clearTimeout(timer.current);
    timer.current = null;
  }

  useEffect(() => () => clearPolling(), []);

  async function connect() {
    if (!clientId.trim()) { setStatus("Inserisci il Client ID per collegare Trakt."); return; }
    clearPolling();
    setBusy(true);
    setStatus("");
    try {
      const next = await startTraktDeviceFlow(clientId);
      const nextAttempt = createTraktDeviceAttempt(
        next,
        clientId.trim(),
        clientSecret,
        Date.now(),
      );
      setAttempt(nextAttempt);
      setStatus("Apri Trakt e inserisci il codice indicato.");
      schedulePoll(nextAttempt);
    } catch (error) { setAttempt(null); setStatus(error instanceof Error ? error.message : "Impossibile avviare Trakt."); setBusy(false); }
  }

  function expireAttempt() {
    clearPolling();
    setAttempt(null);
    setBusy(false);
    setStatus("Codice Trakt scaduto. Riprova.");
  }

  function schedulePoll(current: TraktDeviceAttempt) {
    if (traktDeviceAttemptExpired(current, Date.now())) {
      expireAttempt();
      return;
    }
    const delay = Math.max(2, current.device.interval || 5) * 1_000;
    timer.current = window.setTimeout(() => void poll(current), delay);
  }

  async function poll(current: TraktDeviceAttempt) {
    if (traktDeviceAttemptExpired(current, Date.now())) {
      expireAttempt();
      return;
    }
    try {
      const result = await pollTraktDeviceFlow(
        current.clientId,
        current.clientSecret,
        current.device.device_code,
      );
      if (result.status === "authorized") {
        clearPolling();
        setAttempt(null);
        setBusy(false);
        setStatus("");
        onChanged("Trakt collegato.");
        return;
      }
      schedulePoll(current);
    } catch (error) { clearPolling(); setBusy(false); setAttempt(null); setStatus(error instanceof Error ? error.message : "Collegamento Trakt non riuscito."); }
  }

  async function disconnect() {
    setBusy(true);
    setStatus("");
    try { const result = await clearTraktDeviceFlow(); onChanged(result.message); } catch (error) { setStatus(error instanceof Error ? error.message : "Impossibile scollegare Trakt."); } finally { setBusy(false); }
  }

  function cancel() {
    clearPolling();
    setAttempt(null);
    setBusy(false);
    setStatus("Collegamento Trakt annullato.");
  }

  return <div className="trakt-device-flow">
    <div><span className={connected ? "configuration-state configuration-state--ok" : "configuration-state"}>{connected ? "Collegato" : "Non collegato"}</span>{expiresAt ? <small>Scadenza token: {formatConfigurationMoment(expiresAt)}</small> : null}</div>
    <div className="trakt-device-actions"><Button type="button" variant="secondary" size="compact" onClick={() => void connect()} disabled={disabled || busy}><RefreshCw size={15} className={busy ? "animate-spin" : ""} aria-hidden="true" />Collega Trakt</Button>{attempt ? <Button type="button" variant="ghost" size="compact" onClick={cancel} disabled={disabled}><X size={15} aria-hidden="true" />Annulla collegamento</Button> : <Button type="button" variant="ghost" size="compact" onClick={() => void disconnect()} disabled={disabled || busy || !connected}><Unplug size={15} aria-hidden="true" />Disconnetti</Button>}</div>
    {attempt ? <div className="trakt-device-code"><a href={attempt.device.verification_url} target="_blank" rel="noreferrer">Apri Trakt <ExternalLink size={13} aria-hidden="true" /></a><strong>{attempt.device.user_code}</strong></div> : null}
    {status ? <p>{status}</p> : null}
  </div>;
}

export { TraktDeviceFlow };
