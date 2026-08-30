import { ExternalLink, Send } from "@/components/ui/icons";
import { Link } from "react-router-dom";

import { Button } from "@/components/ui/button";
import { canRequestCollectionItem, formatCollectionDate } from "@/features/collections/presentation";
import type { CollectionSyncDetail, CollectionSyncItem } from "@/features/collections/types";

type CollectionSyncServerDetailProps = {
  detail: CollectionSyncDetail;
  requestKeyPrefix: string;
  requestingKey: string | null;
  onRequest: (item: CollectionSyncItem, key: string) => void;
};

function CollectionSyncServerDetail({ detail, requestKeyPrefix, requestingKey, onRequest }: CollectionSyncServerDetailProps) {
  const items = detail.items || [];

  return (
    <article>
      <header>
        <strong>{detail.server_label || detail.server_id || "Server"}</strong>
        <span>{formatCollectionDate(detail.synced_at)}</span>
      </header>
      <dl>
        <div><dt>Trovati</dt><dd>{detail.matched ?? 0}</dd></div>
        <div><dt>Candidati</dt><dd>{detail.candidates ?? 0}</dd></div>
        <div><dt>Mancanti</dt><dd>{detail.missing ?? 0}</dd></div>
      </dl>
      {detail.message ? <p>{detail.message}</p> : null}
      {items.length ? (
        <details>
          <summary>Elementi elaborati ({items.length})</summary>
          <ul>
            {items.map((item, index) => (
              <CollectionSyncItemRow
                key={`${item.provider_key}:${item.provider_id}:${index}`}
                item={item}
                requestKey={`${requestKeyPrefix}:${index}`}
                requestBlocked={requestingKey !== null}
                requesting={requestingKey === `${requestKeyPrefix}:${index}`}
                onRequest={onRequest}
              />
            ))}
          </ul>
        </details>
      ) : null}
    </article>
  );
}

function CollectionSyncItemRow({ item, requestKey, requestBlocked, requesting, onRequest }: { item: CollectionSyncItem; requestKey: string; requestBlocked: boolean; requesting: boolean; onRequest: CollectionSyncServerDetailProps["onRequest"] }) {
  const itemName = item.title || item.provider_id || "Elemento";
  const title = item.year ? `${itemName} (${item.year})` : itemName;
  const searchQuery = item.title || item.provider_id || "";
  const searchUrl = searchQuery ? `/research?${new URLSearchParams({ independent_query: searchQuery, ...(item.media_type ? { independent_media_type: item.media_type } : {}) }).toString()}` : "";
  const availableForRequest = canRequestCollectionItem(item);

  return (
    <li className={item.found ? "is-found" : "is-missing"}>
      <div className="collection-sync-item-copy">
        <strong>{title}</strong>
        <small>{item.provider_label || item.provider_key || "Provider"}{item.provider_id ? ` · ${item.provider_id}` : ""}</small>
      </div>
      <span className="collection-sync-item-status">{item.found ? "Trovato" : "Mancante"}</span>
      {!item.found ? (
        <span className="collection-sync-item-actions">
          <Button type="button" requiresWriteAccess variant="secondary" size="compact" onClick={() => onRequest(item, requestKey)} disabled={!availableForRequest || requestBlocked} title={!availableForRequest ? "TMDB ID o tipo media non disponibili" : undefined}>
            <Send size={14} aria-hidden="true" />
            {requesting ? "Invio..." : "Jellyseerr"}
          </Button>
          {searchUrl ? <Button asChild type="button" variant="ghost" size="icon"><Link to={searchUrl} aria-label={`Cerca ${searchQuery}`} title={`Cerca ${searchQuery}`}><ExternalLink size={15} aria-hidden="true" /></Link></Button> : null}
        </span>
      ) : null}
    </li>
  );
}

export { CollectionSyncServerDetail };
