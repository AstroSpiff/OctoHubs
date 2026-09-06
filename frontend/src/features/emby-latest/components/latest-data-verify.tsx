import { RefreshCw, SearchCheck, X } from "@/components/ui/icons";
import { useEffect, useMemo, useRef, useState } from "react";

import { Button } from "@/components/ui/button";
import { DialogBackdrop } from "@/components/ui/dialog-backdrop";
import {
  latestVerification,
  type LatestVerification,
} from "@/features/emby-latest/latest-data-availability";
import {
  LatestVerificationCommon,
  LatestVerificationFiles,
} from "@/features/emby-latest/components/latest-verification-fields";
import {
  latestItemSelectionKey,
  reconcileLatestItemSelection,
} from "@/features/emby-latest/latest-item-selection";
import type { LatestItem, LatestServer } from "@/features/emby-latest/types";

function LatestDataVerify({
  open,
  servers,
  movies,
  series,
  enriching,
  error,
  onClose,
  onEnrich,
  onResetError,
}: {
  open: boolean;
  servers: LatestServer[];
  movies: LatestItem[];
  series: LatestItem[];
  enriching: boolean;
  error?: string;
  onClose: () => void;
  onEnrich: (item: LatestItem) => Promise<LatestItem>;
  onResetError: () => void;
}) {
  const [serverId, setServerId] = useState("");
  const [kind, setKind] = useState<"movie" | "series">("movie");
  const [itemKey, setItemKey] = useState("");
  const [enriched, setEnriched] = useState<{ key: string; item: LatestItem }>();
  const [verification, setVerification] = useState<LatestVerification>();
  const generation = useRef(0);
  const snapshotRevision = JSON.stringify({ servers, movies, series });
  const sourceItems = kind === "movie" ? movies : series;
  const items = useMemo(
    () => sourceItems.filter((item) => item.server_id === serverId),
    [serverId, sourceItems],
  );
  const selectionKey = `${serverId}:${kind}:${itemKey}`;
  const activeTarget = useRef("");
  activeTarget.current = open ? selectionKey : "";
  const selected =
    (enriched?.key === selectionKey ? enriched.item : undefined) ||
    items.find(
      (item, index) =>
        latestItemSelectionKey(item, index) === itemKey,
    );

  useEffect(() => {
    setItemKey((current) => {
      if (!current) return current;
      return reconcileLatestItemSelection(items, current);
    });
    setEnriched((current) => {
      if (!current) return current;
      return itemKey &&
        items.some(
          (item, index) => latestItemSelectionKey(item, index) === itemKey,
        )
        && current.key === selectionKey
        ? current
        : undefined;
    });
  }, [itemKey, items, selectionKey]);

  useEffect(() => {
    generation.current += 1;
    setServerId("");
    setKind("movie");
    setItemKey("");
    setEnriched(undefined);
    setVerification(undefined);
    onResetError();
  }, [onResetError, open]);

  useEffect(() => {
    generation.current += 1;
    setEnriched(undefined);
    setVerification(undefined);
    onResetError();
  }, [onResetError, snapshotRevision]);

  function resetSelectionState() {
    generation.current += 1;
    setEnriched(undefined);
    setVerification(undefined);
    onResetError();
  }

  if (!open) return null;
  return (
    <DialogBackdrop
      className="latest-modal-backdrop"
      dismissible={!enriching}
      onDismiss={onClose}
    >
      <section
        className="latest-verify-dialog"
        role="dialog"
        aria-modal="true"
        aria-labelledby="latest-verify-title"
      >
        <header>
          <div>
            <h2 id="latest-verify-title">Verifica dati pubblicazioni</h2>
            <p>
              Controlla i metadati disponibili e aggiorna l'elemento selezionato
              dalle fonti esterne.
            </p>
          </div>
          <Button
            type="button"
            variant="ghost"
            size="icon"
            title="Chiudi"
            aria-label="Chiudi"
            onClick={onClose}
            disabled={enriching}
          >
            <X size={18} aria-hidden="true" />
          </Button>
        </header>
        <div className="latest-verify-filters">
          <label>
            Server
            <select
              value={serverId}
              disabled={enriching}
              onChange={(event) => {
                setServerId(event.target.value);
                setItemKey("");
                resetSelectionState();
              }}
            >
              <option value="">Seleziona un server...</option>
              {servers.map((server) => (
                <option key={server.id} value={server.id}>
                  {server.name}
                </option>
              ))}
            </select>
          </label>
          <label>
            Tipo
            <select
              value={kind}
              disabled={!serverId || enriching}
              onChange={(event) => {
                setKind(event.target.value as "movie" | "series");
                setItemKey("");
                resetSelectionState();
              }}
            >
              <option value="movie">Film</option>
              <option value="series">Serie TV</option>
            </select>
          </label>
          <label>
            Contenuto
            <select
              value={itemKey}
              disabled={!serverId || enriching}
              onChange={(event) => {
                setItemKey(event.target.value);
                resetSelectionState();
              }}
            >
              <option value="">Seleziona contenuto...</option>
              {items.map((item, index) => {
                const key = latestItemSelectionKey(item, index);
                return (
                  <option key={key} value={key}>
                    {item.title || "Titolo"}
                    {item.year ? ` (${item.year})` : ""}
                  </option>
                );
              })}
            </select>
          </label>
        </div>
        {error ? (
          <p className="latest-form-error" role="alert">
            {error}
          </p>
        ) : null}
        {selected ? (
          <>
            <div className="latest-verify-actions">
              <Button
                type="button"
                variant="primary"
                size="compact"
                disabled={enriching}
                onClick={() => setVerification(latestVerification(selected, kind))}
              >
                <SearchCheck size={15} aria-hidden="true" />
                Verifica
              </Button>
              <Button
                type="button"
                requiresWriteAccess
                variant="secondary"
                size="compact"
                disabled={enriching}
                onClick={() => {
                  const baseline = selected;
                  const targetKey = selectionKey;
                  const requestGeneration = ++generation.current;
                  void onEnrich(selected)
                    .then((next) => {
                      if (
                        generation.current !== requestGeneration
                        || activeTarget.current !== targetKey
                      ) return;
                      setEnriched({ key: targetKey, item: next });
                      setVerification(latestVerification(next, kind, baseline));
                    })
                    .catch(() => {
                      if (
                        generation.current !== requestGeneration
                        || activeTarget.current !== targetKey
                      ) onResetError();
                    });
                }}
              >
                <RefreshCw
                  size={15}
                  className={enriching ? "animate-spin" : ""}
                  aria-hidden="true"
                />
                Aggiorna dati
              </Button>
            </div>
            {verification ? (
              <div className="latest-verification-report" aria-live="polite">
                <LatestVerificationCommon verification={verification.common} />
                <LatestVerificationFiles files={verification.files} />
              </div>
            ) : (
              <p className="latest-config-empty">
                Seleziona Verifica per distinguere i dati disponibili da quelli mancanti.
              </p>
            )}
          </>
        ) : (
          <p className="latest-config-empty">
            Seleziona un server e un contenuto per vedere i dati disponibili.
          </p>
        )}
      </section>
    </DialogBackdrop>
  );
}

export { LatestDataVerify };
