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
import { errorMessage, type AuthoritativeSnapshot } from "@/lib/authoritative-snapshot";

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
  const [snapshot, setSnapshot] = useState<
    AuthoritativeSnapshot<CollectionSyncDetail[]> & { targetKey: string }
  >({ status: "pending", targetKey: collection.id });
  const [loadVersion, setLoadVersion] = useState(0);
  const [feedback, setFeedback] = useState<{
    kind: "success" | "error";
    message: string;
  } | null>(null);
  const [requestingKey, setRequestingKey] = useState<string | null>(null);
  const currentSnapshot = snapshot.targetKey === collection.id
    ? snapshot
    : { status: "pending" as const, targetKey: collection.id };

  useEffect(() => {
    let active = true;
    setSnapshot({ status: "pending", targetKey: collection.id });
    setRequestingKey(null);
    setFeedback(null);
    getCollectionSyncDetails(collection.id)
      .then((result) => {
        if (active) {
          setSnapshot({
            status: "success",
            data: result.details || [],
            targetKey: collection.id,
          });
        }
      })
      .catch((reason: unknown) => {
        if (active) {
          setSnapshot({
            status: "error",
            error: errorMessage(reason, "Impossibile caricare i dettagli della sincronizzazione."),
            targetKey: collection.id,
          });
        }
      });
    return () => {
      active = false;
    };
  }, [collection.id, loadVersion]);

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
        {currentSnapshot.status === "pending" ? (
          <p className="user-settings-loading">Caricamento dettagli...</p>
        ) : null}
        {currentSnapshot.status === "error" ? (
          <div className="users-dialog-error" role="alert">
            <span>{currentSnapshot.error}</span>{" "}
            <Button type="button" variant="secondary" size="compact" onClick={() => setLoadVersion((version) => version + 1)}>
              Riprova
            </Button>
          </div>
        ) : null}
        {feedback ? (
          <p
            className={`collection-sync-feedback is-${feedback.kind}`}
            role="status"
          >
            {feedback.message}
          </p>
        ) : null}
        {currentSnapshot.status === "success" ? (
          <CollectionSyncDetailsList
            details={currentSnapshot.data}
            requestingKey={requestingKey}
            onRequest={requestJellyseerr}
          />
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

function CollectionSyncDetailsList({
  details,
  requestingKey,
  onRequest,
}: {
  details: CollectionSyncDetail[];
  requestingKey: string | null;
  onRequest: (item: CollectionSyncItem, key: string) => void;
}) {
  return (
    <>
      <div className="collection-sync-detail-list">
        {details.map((detail, index) => (
          <CollectionSyncServerDetail
            key={`${detail.server_id || detail.server_label}:${index}`}
            detail={detail}
            requestKeyPrefix={`${detail.server_id || detail.server_label || index}`}
            requestingKey={requestingKey}
            onRequest={onRequest}
          />
        ))}
      </div>
      {!details.length ? (
        <p className="collection-source-empty">
          Nessun dettaglio registrato per questa collezione.
        </p>
      ) : null}
    </>
  );
}

export { CollectionSyncDetailsDialog };
