import { X } from "@/components/ui/icons";
import { useEffect, useState } from "react";

import { Button } from "@/components/ui/button";
import { DialogBackdrop } from "@/components/ui/dialog-backdrop";
import {
  requestCollectionItemFromJellyseerr,
  getCollectionSyncDetails,
} from "@/features/collections/api";
import { CollectionSyncServerDetail } from "@/features/collections/components/collection-sync-server-detail";
import type {
  EmbyCollection,
  CollectionSyncItem,
  CollectionSyncDetail,
} from "@/features/collections/types";

function CollectionSyncDetailsDialog({
  collection,
  onClose,
}: {
  collection: EmbyCollection | null;
  onClose: () => void;
}) {
  if (!collection) return null;
  return (
    <CollectionSyncDetailsContent
      key={collection.id}
      collection={collection}
      onClose={onClose}
    />
  );
}

function CollectionSyncDetailsContent({
  collection,
  onClose,
}: {
  collection: EmbyCollection;
  onClose: () => void;
}) {
  const [details, setDetails] = useState<CollectionSyncDetail[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [feedback, setFeedback] = useState<{
    kind: "success" | "error";
    message: string;
  } | null>(null);
  const [requestingKey, setRequestingKey] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    setDetails([]);
    setRequestingKey(null);
    setLoading(true);
    setError("");
    setFeedback(null);
    getCollectionSyncDetails(collection.id)
      .then((result) => {
        if (active) {
          setDetails(result.details || []);
        }
      })
      .catch((reason: Error) => {
        if (active) setError(reason.message);
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, [collection.id]);

  const visibleDetails = details;

  async function requestJellyseerr(item: CollectionSyncItem, key: string) {
    setRequestingKey(key);
    setFeedback(null);
    try {
      const result = await requestCollectionItemFromJellyseerr(item);
      setFeedback({
        kind: "success",
        message: result.message || "Richiesta inviata a Jellyseerr.",
      });
    } catch (reason) {
      setFeedback({
        kind: "error",
        message:
          reason instanceof Error
            ? reason.message
            : "Richiesta Jellyseerr non riuscita.",
      });
    } finally {
      setRequestingKey(null);
    }
  }

  return (
    <DialogBackdrop
      className="users-dialog-backdrop"
      dismissible={!requestingKey}
      onDismiss={onClose}
    >
      <section
        className="collection-sync-dialog"
        role="dialog"
        aria-modal="true"
        aria-labelledby="collection-sync-title"
      >
        <header>
          <div>
            <h2 id="collection-sync-title" className="contextual-heading" title="Esito sincronizzazione">{collection.name}</h2>
          </div>
          <Button
            type="button"
            variant="ghost"
            size="icon"
            title="Chiudi dettagli sincronizzazione"
            aria-label="Chiudi dettagli sincronizzazione"
            onClick={onClose}
            disabled={Boolean(requestingKey)}
          >
            <X size={17} aria-hidden="true" />
          </Button>
        </header>
        {loading ? (
          <p className="user-settings-loading">Caricamento dettagli...</p>
        ) : null}
        {error ? (
          <p className="users-dialog-error" role="alert">
            {error}
          </p>
        ) : null}
        {feedback ? (
          <p
            className={`collection-sync-feedback is-${feedback.kind}`}
            role="status"
          >
            {feedback.message}
          </p>
        ) : null}
        <div className="collection-sync-detail-list">
          {visibleDetails.map((detail, index) => (
            <CollectionSyncServerDetail
              key={`${detail.server_id || detail.server_label}:${index}`}
              detail={detail}
              requestKeyPrefix={`${detail.server_id || detail.server_label || index}`}
              requestingKey={requestingKey}
              onRequest={requestJellyseerr}
            />
          ))}
        </div>
        {!loading && !visibleDetails.length ? (
          <p className="collection-source-empty">
            Nessun dettaglio registrato per questa collezione.
          </p>
        ) : null}
        <footer>
          <Button type="button" variant="primary" onClick={onClose} disabled={Boolean(requestingKey)}>
            Chiudi
          </Button>
        </footer>
      </section>
    </DialogBackdrop>
  );
}

export { CollectionSyncDetailsDialog };
