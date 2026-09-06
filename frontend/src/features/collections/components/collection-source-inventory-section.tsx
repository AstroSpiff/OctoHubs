import { ExternalLink, Plus, RefreshCw, Trash2 } from "@/components/ui/icons";
import { useEffect, useState } from "react";

import { Button } from "@/components/ui/button";
import { QueryStateBoundary } from "@/components/ui/query-state-boundary";
import { WriteAction } from "@/features/session/workspace-capabilities";
import {
  detectCollectionSourceType,
  hasCollectionSourceInventoryDraft,
} from "@/features/collections/collection-source-input";
import type { SourceSelection } from "@/features/collections/collection-source-selection";
import type {
  CollectionOptions,
  CollectionSourceInventoryInput,
  CollectionSourceInventoryItem,
} from "@/features/collections/types";
import { safeExternalHttpUrl } from "@/lib/external-url";

type CollectionSourceInventorySectionProps = {
  options?: CollectionOptions;
  items: CollectionSourceInventoryItem[];
  hasData: boolean;
  refreshing: boolean;
  error?: string;
  busy: boolean;
  onRefresh: () => void;
  onAdd: (input: CollectionSourceInventoryInput) => Promise<void>;
  onChoose: (selection: SourceSelection) => void;
  onDelete: (item: CollectionSourceInventoryItem) => void;
  onDirtyChange?: (dirty: boolean) => void;
};

function CollectionSourceInventorySection({
  options,
  items,
  hasData,
  refreshing,
  error: loadError,
  busy,
  onRefresh,
  onAdd,
  onChoose,
  onDelete,
  onDirtyChange,
}: CollectionSourceInventorySectionProps) {
  const [name, setName] = useState("");
  const [sourceType, setSourceType] = useState("");
  const [sourceValue, setSourceValue] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const activeSourceType = sourceType || options?.source_types[0]?.value || "";
  const disabled = busy || saving;
  const dirty = hasCollectionSourceInventoryDraft(name, sourceValue);

  useEffect(() => {
    onDirtyChange?.(dirty);
    return () => onDirtyChange?.(false);
  }, [dirty, onDirtyChange]);

  async function submit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!activeSourceType || !sourceValue.trim()) {
      setError("Fonte e valore sono obbligatori.");
      return;
    }
    setSaving(true);
    setError("");
    try {
      await onAdd({
        name: name.trim() || undefined,
        source_type: activeSourceType,
        source_value: sourceValue.trim(),
      });
      setName("");
      setSourceValue("");
    } catch (reason) {
      setError(
        reason instanceof Error ? reason.message : "Impossibile salvare la fonte.",
      );
    } finally {
      setSaving(false);
    }
  }

  return (
    <section className="collection-source-section">
      <header>
        <h3>Liste salvate</h3>
        <Button
          type="button"
          variant="ghost"
          size="icon"
          title="Aggiorna liste salvate"
          aria-label="Aggiorna liste salvate"
          onClick={onRefresh}
          disabled={disabled}
        >
          <RefreshCw
            size={15}
            className={refreshing ? "animate-spin" : ""}
            aria-hidden="true"
          />
        </Button>
      </header>
      <WriteAction>
        <form className="collection-source-add" onSubmit={submit}>
        <label className="sr-only" htmlFor="collection-source-name">Nome lista</label>
        <input
          id="collection-source-name"
          value={name}
          disabled={disabled}
          onChange={(event) => setName(event.target.value)}
          placeholder="Nome lista (facoltativo)"
        />
        <label className="sr-only" htmlFor="collection-source-type">Tipo di fonte</label>
        <select
          id="collection-source-type"
          value={activeSourceType}
          disabled={disabled}
          onChange={(event) => setSourceType(event.target.value)}
        >
          {options?.source_types.map((item) => (
            <option key={item.value} value={item.value}>
              {item.label}
            </option>
          ))}
        </select>
        <label className="sr-only" htmlFor="collection-source-value">Link o ID della fonte</label>
        <input
          id="collection-source-value"
          value={sourceValue}
          disabled={disabled}
          onChange={(event) => {
            const value = event.target.value;
            const detectedType = detectCollectionSourceType(value);
            setSourceValue(value);
            if (detectedType) setSourceType(detectedType);
          }}
          placeholder="Link o ID"
        />
        <Button
          type="submit"
          variant="primary"
          size="icon"
          title="Salva fonte"
          aria-label="Salva fonte"
          disabled={disabled}
        >
          <Plus size={16} aria-hidden="true" />
        </Button>
        </form>
      </WriteAction>
      {error ? (
        <p className="users-dialog-error" role="alert">
          {error}
        </p>
      ) : null}
      <QueryStateBoundary
        error={loadError ? new Error(loadError) : null}
        hasData={hasData}
        loadingLabel="Caricamento liste salvate..."
        retrying={refreshing}
        onRetry={onRefresh}
      >
        <CollectionSourceRows
          items={items}
          sourceTypes={options?.source_types || []}
          disabled={disabled}
          onChoose={onChoose}
          onDelete={onDelete}
        />
      </QueryStateBoundary>
    </section>
  );
}

function CollectionSourceRows({
  items,
  sourceTypes,
  disabled,
  onChoose,
  onDelete,
}: {
  items: CollectionSourceInventoryItem[];
  sourceTypes: CollectionOptions["source_types"];
  disabled: boolean;
  onChoose: (selection: SourceSelection) => void;
  onDelete: (item: CollectionSourceInventoryItem) => void;
}) {
  if (!items.length) {
    return <p className="collection-source-empty">Nessuna lista salvata.</p>;
  }

  return (
    <ul className="collection-source-rows">
      {items.map((item) => (
        <li key={item.id}>
          <div>
            <strong>{item.name}</strong>
            <small>
              {sourceTypes.find((source) => source.value === item.source_type)
                ?.label || item.source_type}
              {" · "}
              {item.source_value}
            </small>
          </div>
          <span>
            <Button
              type="button"
              requiresWriteAccess
              variant="secondary"
              size="compact"
              disabled={disabled}
              onClick={() =>
                onChoose({
                  sourceType: item.source_type,
                  sourceValue: item.source_value,
                  sourceOrigin: "inventory",
                })
              }
            >
              Usa
            </Button>
            {safeExternalHttpUrl(item.source_link) ? (
              <a
                href={safeExternalHttpUrl(item.source_link) || undefined}
                target="_blank"
                rel="noreferrer"
                title="Apri lista"
                aria-label={`Apri ${item.name}`}
              >
                <ExternalLink size={16} aria-hidden="true" />
              </a>
            ) : null}
            <Button
              type="button"
              requiresWriteAccess
              variant="ghost"
              size="icon"
              title="Elimina fonte"
              aria-label={`Elimina fonte ${item.name}`}
              onClick={() => onDelete(item)}
              disabled={disabled}
            >
              <Trash2 size={15} aria-hidden="true" />
            </Button>
          </span>
        </li>
      ))}
    </ul>
  );
}

export { CollectionSourceInventorySection };
