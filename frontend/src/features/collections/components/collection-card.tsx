import { Bot, CalendarRange, CircleEllipsis, Database, ExternalLink, ListChecks, Pencil, RefreshCw, Server, ToggleLeft, ToggleRight, Trash2 } from "@/components/ui/icons";
import { useRef, useState } from "react";

import { StatusBadge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { collectionMarkers, collectionPosterUrl, collectionSyncLabel, collectionSyncSeverity, formatCollectionDate } from "@/features/collections/presentation";
import { EmbyServerIcon } from "@/features/emby-live/components/emby-server-icon";
import type { CollectionServer, CollectionSyncDetail, EmbyCollection } from "@/features/collections/types";
import { safeExternalHttpUrl } from "@/lib/external-url";

type CollectionCardProps = {
  collection: EmbyCollection;
  changing: boolean;
  syncing: boolean;
  syncingAll: boolean;
  actionError?: string;
  onToggle: (collection: EmbyCollection) => void;
  onSync: (collection: EmbyCollection) => void;
  onEdit: (collection: EmbyCollection) => void;
  onDetails: (collection: EmbyCollection) => void;
  onDelete: (collection: EmbyCollection) => void;
};

type CollectionSyncRow = {
  key: string;
  name: string;
  server?: CollectionServer;
  syncedAt: string | null;
};

type CollectionElementRow = {
  key: string;
  name: string;
  server?: CollectionServer;
  matched: number | null;
  candidates: number | null;
  missing: number | null;
};

function CollectionCard({ collection, changing, syncing, syncingAll, actionError, onToggle, onSync, onEdit, onDetails, onDelete }: CollectionCardProps) {
  const [flipped, setFlipped] = useState(false);
  const frontRef = useRef<HTMLButtonElement>(null);
  const closeRef = useRef<HTMLButtonElement>(null);
  const poster = collectionPosterUrl(collection);
  const status = collection.delete_pending ? "Da rimuovere" : collection.enabled ? collectionSyncLabel(collection.last_sync_status) : "Disabilitata";
  const severity = collection.delete_pending || !collection.enabled ? "neutral" : collectionSyncSeverity(collection.last_sync_status);
  const servers = collection.servers || [];
  const markers = collectionMarkers(collection).filter((marker) => servers.length || marker.kind !== "servers");
  const serverResults = collection.last_sync_per_server || [];
  const syncRows = collectionSyncRows(collection, servers);
  const elementRows = collectionElementRows(collection, servers);
  const visibleResultCount = serverResults.filter((result) => typeof result.candidates === "number" || typeof result.matched === "number").length;
  const showSyncMessage = Boolean(collection.last_sync_message && !visibleResultCount);
  const actionsDisabled = changing || syncing || collection.delete_pending;
  const sourceLabel = collection.source_label || collection.source_display || "Non disponibile";
  const sortTitle = collection.sort_name || collection.collection_sort_name || collection.name;

  function openDetails() {
    setFlipped(true);
    window.requestAnimationFrame(() => closeRef.current?.focus());
  }

  function closeDetails() {
    setFlipped(false);
    window.requestAnimationFrame(() => frontRef.current?.focus());
  }

  return (
    <article className={`collection-card ${collection.enabled ? "" : "is-disabled"} ${flipped ? "is-flipped" : ""}`}>
      <div
        className="collection-card-flip"
        onPointerLeave={() => {
          if (!document.activeElement || !closeRef.current?.closest(".collection-card-back")?.contains(document.activeElement)) {
            setFlipped(false);
          }
        }}
      >
        <div className="collection-card-inner">
          <button
            ref={frontRef}
            type="button"
            className="collection-card-front"
            onClick={openDetails}
            aria-label={`Apri dettagli di ${collection.name}`}
            aria-expanded={flipped}
            aria-hidden={flipped || undefined}
            inert={flipped ? true : undefined}
          >
            <StatusBadge severity={severity}>{status}</StatusBadge>
            {poster ? <img src={poster} alt="" loading="lazy" onError={(event) => { event.currentTarget.hidden = true; }} /> : null}
            {poster ? null : <span className="collection-card-poster-placeholder"><Database size={42} aria-hidden="true" /></span>}
          </button>

          <section
            className="collection-card-back"
            aria-label={`Azioni e dettagli di ${collection.name}`}
            aria-hidden={!flipped || undefined}
            onKeyDown={(event) => {
              if (event.key === "Escape") closeDetails();
            }}
            inert={!flipped ? true : undefined}
          >
            <header>
              <div>
                <span>Sort title</span>
                <h2>{sortTitle}</h2>
              </div>
              <div className="collection-card-heading-actions">
                <Button ref={closeRef} type="button" variant="ghost" size="compact" onClick={closeDetails}>Chiudi</Button>
                <Button type="button" requiresWriteAccess variant="ghost" size="icon" title="Modifica collezione" aria-label={`Modifica ${collection.name}`} onClick={() => onEdit(collection)} disabled={actionsDisabled}><Pencil size={15} aria-hidden="true" /></Button>
                <Button type="button" variant="ghost" size="icon" title="Dettagli sincronizzazione" aria-label={`Dettagli sincronizzazione ${collection.name}`} onClick={() => onDetails(collection)}><CircleEllipsis size={16} aria-hidden="true" /></Button>
                <Button type="button" requiresWriteAccess variant="ghost" size="icon" title="Elimina collezione" aria-label={`Elimina ${collection.name}`} onClick={() => onDelete(collection)} disabled={actionsDisabled}><Trash2 size={15} aria-hidden="true" /></Button>
              </div>
          </header>

          <dl className="collection-meta">
            {collection.collection_description ? <div className="collection-meta-wide"><dt>Descrizione</dt><dd>{collection.collection_description}</dd></div> : null}
            <div>
              <dt>Fonte</dt>
              <dd className="collection-source-summary">
                <span>{sourceLabel}</span>
                {safeExternalHttpUrl(collection.source_link) ? (
                  <a href={safeExternalHttpUrl(collection.source_link) || undefined} target="_blank" rel="noreferrer" title={collection.source_display || collection.source_value || sourceLabel} aria-label={`Apri fonte ${sourceLabel}`}>
                    <ExternalLink size={13} aria-hidden="true" />
                  </a>
                ) : null}
              </dd>
            </div>
            <div>
              <dt>Server</dt>
              <dd className="collection-server-list">
                {servers.length ? servers.map((server) => <CollectionServerBadge key={server.id} server={server} />) : (
                  <span><Server size={14} className="collection-server-icon" aria-hidden="true" />{collection.server_display || "Nessun server"}</span>
                )}
              </dd>
            </div>
            <div>
              <dt>Ultima sync</dt>
              <dd className="collection-sync-list">
                {syncRows.map((row) => (
                  <span key={row.key} className="collection-sync-server" title={`${row.name}: ${formatCollectionDate(row.syncedAt)}`}>
                    <EmbyServerIcon icon={row.server?.icon} color={row.server?.icon_color} iconStyle={row.server?.icon_style} size={13} />
                    <CollectionSyncTime value={row.syncedAt} />
                  </span>
                ))}
              </dd>
            </div>
            <div>
              <dt>Elementi</dt>
              <dd className="collection-result-list">
                {elementRows.map((row) => (
                  <span key={row.key} className="collection-result-server" title={`${row.name}: ${formatElementResult(row)}`}>
                    <EmbyServerIcon icon={row.server?.icon} color={row.server?.icon_color} iconStyle={row.server?.icon_style} size={13} />
                    <span>{formatElementResult(row)}</span>
                    {typeof row.missing === "number" && row.missing > 0 ? <small>{row.missing} manc.</small> : null}
                  </span>
                ))}
                {visibleResultCount ? <button type="button" className="collection-result-summary" onClick={() => onDetails(collection)} title="Apri risultati per server"><ListChecks size={12} aria-hidden="true" />{visibleResultCount}</button> : null}
              </dd>
            </div>
          </dl>

          {showSyncMessage ? <p className="collection-card-message">{collection.last_sync_message}</p> : null}
          {syncing ? <p className="collection-card-operation-status" role="status">{syncingAll ? "Sincronizzazione globale in corso..." : "Sincronizzazione in corso..."}</p> : null}
          {actionError ? <p className="collection-card-message inline-alert inline-alert--error" role="alert">{actionError}</p> : null}
          <footer className="collection-card-actions">
            <Button type="button" requiresWriteAccess variant="secondary" size="compact" onClick={() => onToggle(collection)} disabled={actionsDisabled}>
              {collection.enabled ? <ToggleRight size={17} aria-hidden="true" /> : <ToggleLeft size={17} aria-hidden="true" />}
              {collection.enabled ? "Disabilita" : "Abilita"}
            </Button>
            <Button type="button" requiresWriteAccess variant="primary" size="compact" onClick={() => onSync(collection)} disabled={actionsDisabled}>
              <RefreshCw size={16} className={syncing ? "animate-spin" : ""} aria-hidden="true" />
              Sincronizza
            </Button>
          </footer>
          </section>
        </div>
      </div>
      <div className="collection-card-front-summary">
        <strong>{collection.name}</strong>
        {servers.length ? <span className="collection-card-front-servers" aria-label="Server collezione">{servers.map((server) => <CollectionServerBadge key={server.id} server={server} compact />)}</span> : null}
        {markers.length ? <span className="collection-card-front-meta" aria-label="Proprietà collezione">{markers.map((marker) => <CollectionMarkerBadge key={marker.kind} kind={marker.kind} label={marker.label} />)}</span> : null}
      </div>
    </article>
  );
}

function CollectionServerBadge({ server, compact = false }: { server: CollectionServer; compact?: boolean }) {
  return (
    <span className={`collection-server-badge${compact ? " collection-server-badge--compact" : ""}`} title={server.name}>
      <EmbyServerIcon icon={server.icon} color={server.icon_color} iconStyle={server.icon_style} size={compact ? 12 : 14} />
      {compact ? <small>{server.name}</small> : server.name}
    </span>
  );
}

function CollectionSyncTime({ value }: { value: string | null }) {
  const parts = collectionDateParts(value);
  if (!parts) return <time dateTime={value || undefined}>{formatCollectionDate(value)}</time>;
  return (
    <time dateTime={value || undefined} className="collection-sync-time">
      <span>{parts.date}</span>
      <span>{parts.time}</span>
    </time>
  );
}

function collectionDateParts(value?: string | null): { date: string; time: string } | null {
  if (!value) return null;
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return null;
  return {
    date: new Intl.DateTimeFormat("it-IT", {
      day: "2-digit",
      month: "2-digit",
      year: "numeric",
    }).format(date),
    time: new Intl.DateTimeFormat("it-IT", {
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit",
    }).format(date),
  };
}

function collectionSyncRows(collection: EmbyCollection, servers: CollectionServer[]): CollectionSyncRow[] {
  const details = collection.last_sync_per_server || [];
  const detailByServer = new Map<string, CollectionSyncDetail>();
  details.forEach((detail) => {
    if (detail.server_id) detailByServer.set(detail.server_id, detail);
  });
  if (servers.length) {
    return servers.map((server) => {
      const detail = detailByServer.get(server.id);
      const fallbackDate = details.length ? null : collection.last_sync_at;
      return {
        key: server.id,
        name: server.name,
        server,
        syncedAt: detail?.synced_at || fallbackDate || null,
      };
    });
  }
  if (details.length) {
    return details.map((detail, index) => ({
      key: detail.server_id || `server-${index}`,
      name: detail.server_label || detail.server_id || "Server",
      server: detail.server_id ? { id: detail.server_id, name: detail.server_label || detail.server_id } : undefined,
      syncedAt: detail.synced_at || null,
    }));
  }
  return [{ key: "global", name: "Globale", server: undefined, syncedAt: collection.last_sync_at || null }];
}

function collectionElementRows(collection: EmbyCollection, servers: CollectionServer[]): CollectionElementRow[] {
  const details = collection.last_sync_per_server || [];
  const detailByServer = new Map<string, CollectionSyncDetail>();
  details.forEach((detail) => {
    if (detail.server_id) detailByServer.set(detail.server_id, detail);
  });
  if (servers.length) {
    return servers.map((server) => {
      const detail = detailByServer.get(server.id);
      const fallbackMatched = details.length ? null : collection.last_sync_items;
      const fallbackCandidates = details.length ? null : collection.last_sync_candidates;
      return {
        key: server.id,
        name: server.name,
        server,
        matched: detail?.matched ?? fallbackMatched ?? null,
        candidates: detail?.candidates ?? fallbackCandidates ?? null,
        missing: detail?.missing ?? null,
      };
    });
  }
  if (details.length) {
    return details.map((detail, index) => ({
      key: detail.server_id || `server-${index}`,
      name: detail.server_label || detail.server_id || "Server",
      server: detail.server_id ? { id: detail.server_id, name: detail.server_label || detail.server_id } : undefined,
      matched: detail.matched ?? null,
      candidates: detail.candidates ?? null,
      missing: detail.missing ?? null,
    }));
  }
  return [{
    key: "global",
    name: "Globale",
    server: undefined,
    matched: collection.last_sync_items ?? null,
    candidates: collection.last_sync_candidates ?? null,
    missing: null,
  }];
}

function formatElementResult(row: { matched: number | null; candidates: number | null }) {
  if (typeof row.matched === "number" && typeof row.candidates === "number") return `${row.matched}/${row.candidates}`;
  if (typeof row.matched === "number") return String(row.matched);
  if (typeof row.candidates === "number") return `0/${row.candidates}`;
  return "Mai";
}

function CollectionMarkerBadge({ kind, label }: { kind: ReturnType<typeof collectionMarkers>[number]["kind"]; label: string }) {
  const Icon = kind === "servers" ? Server : kind === "season" ? CalendarRange : kind === "automation" ? Bot : Database;
  return <span className={`collection-marker collection-marker--${kind}`} title={label}><Icon size={12} aria-hidden="true" />{label}</span>;
}

export { CollectionCard };
