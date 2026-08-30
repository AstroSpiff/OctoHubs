import { RefreshCw, SearchCheck, X } from "@/components/ui/icons";
import { useEffect, useMemo, useState } from "react";

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
}: {
  open: boolean;
  servers: LatestServer[];
  movies: LatestItem[];
  series: LatestItem[];
  enriching: boolean;
  error?: string;
  onClose: () => void;
  onEnrich: (item: LatestItem) => Promise<LatestItem>;
}) {
  const [serverId, setServerId] = useState("");
  const [kind, setKind] = useState<"movie" | "series">("movie");
  const [itemKey, setItemKey] = useState("");
  const [enriched, setEnriched] = useState<LatestItem>();
  const [verification, setVerification] = useState<LatestVerification>();
  const sourceItems = kind === "movie" ? movies : series;
  const items = useMemo(
    () => sourceItems.filter((item) => item.server_id === serverId),
    [serverId, sourceItems],
  );
  const selected =
    enriched ||
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
        ? current
        : undefined;
    });
  }, [itemKey, items]);

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
                setEnriched(undefined);
                setVerification(undefined);
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
                setEnriched(undefined);
                setVerification(undefined);
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
                setEnriched(undefined);
                setVerification(undefined);
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
                  void onEnrich(selected)
                    .then((next) => {
                      setEnriched(next);
                      setVerification(latestVerification(next, kind, baseline));
                    })
                    .catch(() => undefined);
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
