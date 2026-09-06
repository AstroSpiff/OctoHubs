import { ExternalLink, RefreshCw, Unplug, X } from "@/components/ui/icons";
import { useEffect } from "react";

import { Button } from "@/components/ui/button";
import { formatConfigurationMoment } from "@/features/configuration/automation-presentation";
import { useTraktDeviceFlow } from "@/features/configuration/use-trakt-device-flow";
import { safeExternalHttpUrl } from "@/lib/external-url";

function TraktDeviceFlow({ clientId, clientSecret, connected, expiresAt, disabled, onChanged, onBusyChange }: { clientId: string; clientSecret: string; connected: boolean; expiresAt: string; disabled: boolean; onChanged: (message: string) => void; onBusyChange?: (busy: boolean) => void }) {
  const { attempt, busy, cancel, connect, disconnect, status, statusKind } = useTraktDeviceFlow({
    clientId,
    clientSecret,
    disabled,
    onChanged,
  });

  useEffect(() => {
    onBusyChange?.(busy);
    return () => onBusyChange?.(false);
  }, [busy, onBusyChange]);

  return <div className="trakt-device-flow">
    <div><span className={connected ? "configuration-state configuration-state--ok" : "configuration-state"}>{connected ? "Collegato" : "Non collegato"}</span>{expiresAt ? <small>Scadenza token: {formatConfigurationMoment(expiresAt)}</small> : null}</div>
    <div className="trakt-device-actions"><Button type="button" variant="secondary" size="compact" onClick={() => void connect()} disabled={disabled || busy}><RefreshCw size={15} className={busy ? "animate-spin" : ""} aria-hidden="true" />Collega Trakt</Button>{attempt ? <Button type="button" variant="ghost" size="compact" onClick={cancel} disabled={disabled}><X size={15} aria-hidden="true" />Annulla collegamento</Button> : <Button type="button" variant="ghost" size="compact" onClick={() => void disconnect()} disabled={disabled || busy || !connected}><Unplug size={15} aria-hidden="true" />Disconnetti</Button>}</div>
    <div role={statusKind === "error" ? "alert" : "status"} aria-live={statusKind === "error" ? "assertive" : "polite"} aria-atomic="true">
      {attempt ? <div className="trakt-device-code">{safeExternalHttpUrl(attempt.device.verification_url) ? <a href={safeExternalHttpUrl(attempt.device.verification_url) || undefined} target="_blank" rel="noreferrer">Apri Trakt <ExternalLink size={13} aria-hidden="true" /></a> : null}<strong aria-label={`Codice Trakt ${attempt.device.user_code}`}>{attempt.device.user_code}</strong></div> : null}
      {status ? <p>{status}</p> : null}
    </div>
  </div>;
}

export { TraktDeviceFlow };
