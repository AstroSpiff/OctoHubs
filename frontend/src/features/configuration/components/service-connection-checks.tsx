import type { ConnectionCheckPayload } from "@/features/configuration/types";
import { serviceLabel } from "@/features/configuration/service-settings-model";

function ServiceConnectionChecks({ statuses }: { statuses: ConnectionCheckPayload["statuses"] }) {
  const visibleStatuses = Object.entries(statuses).filter(([name]) => (
    name !== "qbittorrent" || !("torrent_clients" in statuses)
  ));
  return <section className="connection-checks" aria-live="polite">
    <h3>Verifica connessioni</h3>
    <div>{visibleStatuses.map(([name, status]) => <article key={name} className={status.ok ? "connection-check connection-check--ok" : "connection-check"}>
      <strong>{serviceLabel(name)}</strong>
      <span>{status.ok ? "Raggiungibile" : status.configured === false ? "Non configurato" : "Non raggiungibile"}</span>
      <p>{status.message}</p>
    </article>)}</div>
  </section>;
}

export { ServiceConnectionChecks };
