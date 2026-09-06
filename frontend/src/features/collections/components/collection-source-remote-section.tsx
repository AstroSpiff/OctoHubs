import { ExternalLink, RefreshCw } from "@/components/ui/icons";

import { Button } from "@/components/ui/button";
import { safeCollectionProviderLink } from "@/features/collections/collection-provider-links";
import type { SourceSelection } from "@/features/collections/collection-source-selection";
import type { PersonalCollectionList } from "@/features/collections/types";

type CollectionSourceRemoteSectionProps = {
  title: string;
  defaultSourceType: string;
  unavailable: boolean;
  loading: boolean;
  busy: boolean;
  error?: string;
  items: PersonalCollectionList[];
  onRefresh: () => void;
  onChoose: (selection: SourceSelection) => void;
};

function CollectionSourceRemoteSection({
  title,
  defaultSourceType,
  unavailable,
  loading,
  busy,
  error,
  items,
  onRefresh,
  onChoose,
}: CollectionSourceRemoteSectionProps) {
  return (
    <section className="collection-source-section">
      <header>
        <h3>{title}</h3>
        <Button
          type="button"
          requiresWriteAccess
          variant="ghost"
          size="icon"
          title={`Aggiorna ${title}`}
          aria-label={`Aggiorna ${title}`}
          onClick={onRefresh}
          disabled={unavailable || loading || busy}
        >
          <RefreshCw
            size={15}
            className={loading ? "animate-spin" : ""}
            aria-hidden="true"
          />
        </Button>
      </header>
      {unavailable ? (
        <p className="collection-source-empty">Servizio non configurato.</p>
      ) : error ? (
        <p className="users-dialog-error" role="alert">
          {error}
        </p>
      ) : !items.length && !loading ? (
        <p className="collection-source-empty">Nessuna lista disponibile.</p>
      ) : (
        <ul className="collection-source-rows">
          {items.map((item, index) => {
            const sourceValue = collectionListSourceValue(item);
            const label = item.name || item.title || sourceValue;
            const link = safeCollectionProviderLink(
              item.url || item.link,
              item.source_type || defaultSourceType,
            );
            return (
              <li key={`${sourceValue}:${index}`}>
                <div>
                  <strong>{label}</strong>
                  <small>
                    {item.item_count ?? item.count ?? 0} elementi
                    {item.description ? ` · ${item.description}` : ""}
                  </small>
                </div>
                <span>
                  {link ? (
                    <a
                      href={link}
                      target="_blank"
                      rel="noreferrer"
                      title="Apri lista"
                      aria-label={`Apri ${label}`}
                    >
                      <ExternalLink size={16} aria-hidden="true" />
                    </a>
                  ) : null}
                  <Button
                    type="button"
                    requiresWriteAccess
                    variant="secondary"
                    size="compact"
                    onClick={() =>
                      onChoose({
                        sourceType: item.source_type || defaultSourceType,
                        sourceValue,
                        sourceOrigin: "personal",
                      })
                    }
                    disabled={busy}
                  >
                    Usa
                  </Button>
                </span>
              </li>
            );
          })}
        </ul>
      )}
    </section>
  );
}

function collectionListSourceValue(item: PersonalCollectionList) {
  return item.source_value || item.value || item.url || "";
}

export { CollectionSourceRemoteSection };
