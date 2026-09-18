import { ChevronRight, RefreshCw, Trash2 } from "@/components/ui/icons";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { Button } from "@/components/ui/button";
import { getProbeQueueGroupItems } from "@/features/probe/api";
import { probeItemLabel } from "@/features/probe/presentation";
import type {
  ProbeQueueGroup,
  ProbeQueueItem,
  ProbeScope,
} from "@/features/probe/types";

type QueueLibraryGroup = {
  id: string;
  label: string;
  fileCount: number;
  groups: ProbeQueueGroup[];
};

function ProbeQueueGroups({
  groups,
  scope,
  serverNames,
  busy,
  onRemove,
}: {
  groups: ProbeQueueGroup[];
  scope: ProbeScope;
  serverNames: Record<string, string>;
  busy: boolean;
  onRemove: (item: ProbeQueueItem) => Promise<void>;
}) {
  const libraries = useMemo(
    () => groupQueueTitlesByLibrary(groups, serverNames),
    [groups, serverNames],
  );
  const [activeGroup, setActiveGroup] = useState<ProbeQueueGroup | null>(null);
  const [items, setItems] = useState<ProbeQueueItem[] | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [requestVersion, setRequestVersion] = useState(0);
  const requestGeneration = useRef(0);
  const abortController = useRef<AbortController | null>(null);
  const activeKey = activeGroup ? probeQueueGroupKey(activeGroup) : null;

  const clearActiveGroup = useCallback(() => {
    requestGeneration.current += 1;
    abortController.current?.abort();
    abortController.current = null;
    setActiveGroup(null);
    setItems(null);
    setLoading(false);
    setError(null);
  }, []);

  useEffect(() => {
    if (!activeKey) return;
    if (!groups.some((group) => probeQueueGroupKey(group) === activeKey)) {
      clearActiveGroup();
    }
  }, [activeKey, clearActiveGroup, groups]);

  useEffect(() => {
    if (!activeGroup) return;
    const controller = new AbortController();
    abortController.current = controller;
    const generation = requestGeneration.current + 1;
    requestGeneration.current = generation;
    setItems(null);
    setError(null);
    setLoading(true);

    void getProbeQueueGroupItems(activeGroup, scope, controller.signal)
      .then((response) => {
        if (requestGeneration.current !== generation) return;
        setItems(response.queue);
        setLoading(false);
      })
      .catch((reason: unknown) => {
        if (controller.signal.aborted || requestGeneration.current !== generation) return;
        setError(
          reason instanceof Error
            ? reason.message
            : "Dettaglio coda non disponibile.",
        );
        setLoading(false);
      });

    return () => controller.abort();
  }, [activeGroup, requestVersion, scope]);

  function toggleGroup(group: ProbeQueueGroup) {
    const nextKey = probeQueueGroupKey(group);
    if (activeKey === nextKey) {
      clearActiveGroup();
      return;
    }
    clearActiveGroup();
    setActiveGroup(group);
  }

  async function removeItem(item: ProbeQueueItem) {
    await onRemove(item);
    clearActiveGroup();
  }

  return (
    <div className="probe-library-groups">
      {libraries.map((library) => (
        <details
          key={library.id}
          className="probe-library-group"
          onToggle={(event) => {
            if (
              !event.currentTarget.open &&
              activeGroup &&
              library.groups.some(
                (group) => probeQueueGroupKey(group) === activeKey,
              )
            ) {
              clearActiveGroup();
            }
          }}
        >
          <summary>
            <span>
              <ChevronRight size={16} aria-hidden="true" />
              {library.label}
            </span>
            <strong>{fileCountLabel(library.fileCount)}</strong>
          </summary>
          <div className="probe-library-group-content probe-queue-groups">
            {library.groups.map((group) => {
              const key = probeQueueGroupKey(group);
              const expanded = activeKey === key;
              const detailId = `probe-queue-details-${safeDomId(key)}`;
              return (
                <article key={key} className="probe-queue-title-group">
                  <button
                    type="button"
                    className="probe-queue-title-summary"
                    aria-expanded={expanded}
                    aria-controls={detailId}
                    onClick={() => toggleGroup(group)}
                  >
                    <span>
                      <ChevronRight size={15} aria-hidden="true" />
                      <span>
                        <strong>{queueGroupLabel(group)}</strong>
                        <small>
                          {group.group_type === "series" ? "Serie TV" : "Film"}
                        </small>
                      </span>
                    </span>
                    <strong>{fileCountLabel(group.file_count)}</strong>
                  </button>
                  {expanded ? (
                    <div id={detailId} className="probe-queue-title-details">
                      {loading ? (
                        <p className="probe-queue-detail-state" role="status">
                          Caricamento file da trattare...
                        </p>
                      ) : null}
                      {error ? (
                        <div className="probe-queue-detail-error" role="alert">
                          <span>{error}</span>
                          <Button
                            type="button"
                            variant="secondary"
                            size="compact"
                            onClick={() =>
                              setRequestVersion((value) => value + 1)
                            }
                          >
                            <RefreshCw size={14} aria-hidden="true" />
                            Riprova
                          </Button>
                        </div>
                      ) : null}
                      {!loading && !error && items?.length === 0 ? (
                        <p className="probe-queue-detail-state">
                          Nessun file ancora presente nella coda.
                        </p>
                      ) : null}
                      {items?.map((item, index) => (
                        <ProbeQueueRow
                          key={`${item.item_id}:${item.media_source_id || index}`}
                          item={item}
                          busy={busy}
                          onRemove={removeItem}
                        />
                      ))}
                    </div>
                  ) : null}
                </article>
              );
            })}
          </div>
        </details>
      ))}
    </div>
  );
}

function ProbeQueueRow({
  item,
  busy,
  onRemove,
}: {
  item: ProbeQueueItem;
  busy: boolean;
  onRemove: (item: ProbeQueueItem) => Promise<void>;
}) {
  return (
    <article className="probe-queue-row">
      <div>
        <strong>{probeItemLabel(item)}</strong>
        <span>{item.path || "Percorso non disponibile"}</span>
      </div>
      <Button
        type="button"
        requiresWriteAccess
        variant="ghost"
        size="compact"
        title="Rimuovi dalla coda"
        onClick={() => void onRemove(item)}
        disabled={busy}
      >
        <Trash2 size={14} aria-hidden="true" />
        Rimuovi
      </Button>
    </article>
  );
}

function groupQueueTitlesByLibrary(
  groups: ProbeQueueGroup[],
  serverNames: Record<string, string>,
): QueueLibraryGroup[] {
  const libraries = new Map<string, QueueLibraryGroup>();
  groups.forEach((group) => {
    const libraryName = group.library_name || "Libreria sconosciuta";
    const serverName = serverNames[group.server_id] || "";
    const id = `${group.server_id}:${group.library_id || libraryName}`;
    const library = libraries.get(id) || {
      id,
      label: serverName ? `${serverName} - ${libraryName}` : libraryName,
      fileCount: 0,
      groups: [],
    };
    library.fileCount += group.file_count;
    library.groups.push(group);
    libraries.set(id, library);
  });
  return [...libraries.values()]
    .map((library) => ({
      ...library,
      groups: library.groups.sort((left, right) =>
        queueGroupLabel(left).localeCompare(queueGroupLabel(right), "it"),
      ),
    }))
    .sort((left, right) => left.label.localeCompare(right.label, "it"));
}

function probeQueueGroupKey(group: ProbeQueueGroup) {
  return JSON.stringify([
    group.server_id,
    group.library_id || "",
    group.group_type,
    group.group_id,
    group.group_type === "series" ? group.year || null : null,
  ]);
}

function queueGroupLabel(group: ProbeQueueGroup) {
  return group.year && !/\(\d{4}\)/.test(group.title)
    ? `${group.title} (${group.year})`
    : group.title;
}

function fileCountLabel(count: number) {
  return `${count} file`;
}

function safeDomId(value: string) {
  let hash = 2166136261;
  for (let index = 0; index < value.length; index += 1) {
    hash ^= value.charCodeAt(index);
    hash = Math.imul(hash, 16777619);
  }
  return (hash >>> 0).toString(36);
}

export { ProbeQueueGroups };
