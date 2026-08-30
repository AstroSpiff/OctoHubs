import { Search, X } from "@/components/ui/icons";
import { useEffect, useMemo, useRef, useState } from "react";

import { Button } from "@/components/ui/button";
import { DialogBackdrop } from "@/components/ui/dialog-backdrop";
import {
  latestTemplateTokens,
  type LatestTemplateToken,
} from "@/features/emby-latest/latest-template-token-catalog";

function LatestTemplateTokenDialog({
  open,
  onClose,
  onSelect,
}: {
  open: boolean;
  onClose: () => void;
  onSelect: (token: string) => void;
}) {
  const [query, setQuery] = useState("");
  const searchRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (!open) return;
    setQuery("");
    window.requestAnimationFrame(() => searchRef.current?.focus());
  }, [onClose, open]);

  const groups = useMemo(() => {
    const normalizedQuery = query.trim().toLocaleLowerCase("it-IT");
    const entries = latestTemplateTokens.filter((entry) =>
      [entry.token, entry.label, entry.description, entry.group]
        .join(" ")
        .toLocaleLowerCase("it-IT")
        .includes(normalizedQuery),
    );
    return entries.reduce<Record<string, LatestTemplateToken[]>>(
      (all, entry) => {
        (all[entry.group] ||= []).push(entry);
        return all;
      },
      {},
    );
  }, [query]);

  if (!open) return null;

  return (
    <DialogBackdrop className="latest-modal-backdrop" onDismiss={onClose}>
      <section
        className="latest-token-dialog"
        role="dialog"
        aria-modal="true"
        aria-labelledby="latest-token-dialog-title"
      >
        <header>
          <div>
            <h2 id="latest-token-dialog-title">Catalogo pattern</h2>
            <p>Seleziona un pattern per inserirlo nel punto del cursore.</p>
          </div>
          <Button
            type="button"
            variant="ghost"
            size="icon"
            title="Chiudi catalogo"
            aria-label="Chiudi catalogo"
            onClick={onClose}
          >
            <X size={17} aria-hidden="true" />
          </Button>
        </header>
        <label className="latest-token-search">
          <Search size={16} aria-hidden="true" />
          <input
            ref={searchRef}
            type="search"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="Cerca titolo, immagine, audio, Jellyseerr..."
          />
        </label>
        <div className="latest-token-groups">
          {Object.entries(groups).map(([group, entries]) => (
            <section key={group}>
              <h3>{group}</h3>
              <div>
                {entries.map((entry) => (
                  <button
                    key={entry.token}
                    type="button"
                    className="latest-token-row"
                    onClick={() => onSelect(entry.token)}
                  >
                    <code>{entry.token}</code>
                    <span>
                      <strong>{entry.label}</strong>
                      <small>{entry.description}</small>
                    </span>
                    <em>Esempio: {entry.example}</em>
                  </button>
                ))}
              </div>
            </section>
          ))}
          {!Object.keys(groups).length ? (
            <p className="latest-token-empty">Nessun pattern corrispondente.</p>
          ) : null}
        </div>
      </section>
    </DialogBackdrop>
  );
}

export { LatestTemplateTokenDialog };
