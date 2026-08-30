import {
  History,
  ListTodo,
  RotateCcw,
  ShieldAlert,
  Trash2,
} from "@/components/ui/icons";
import type { ReactNode } from "react";

import { Button } from "@/components/ui/button";
import { ProbeLibraryGroups } from "@/features/probe/components/probe-library-groups";
import { ProbeQueueGroups } from "@/features/probe/components/probe-queue-groups";
import { ProbeRecordList } from "@/features/probe/components/probe-record-list";
import type {
  ProbeBlacklistItem,
  ProbeHistoryItem,
  ProbeQueueItem,
} from "@/features/probe/types";

function ProbeQueuePanel({
  items,
  serverNames,
  busy,
  onClear,
  onRemove,
}: {
  items: ProbeQueueItem[];
  serverNames: Record<string, string>;
  busy: boolean;
  onClear: () => void;
  onRemove: (item: ProbeQueueItem) => void;
}) {
  return (
    <ProbeList
      icon={<ListTodo size={16} aria-hidden="true" />}
      title="Coda di analisi"
      empty="La coda è vuota."
      isEmpty={!items.length}
      actions={
        <Button
          type="button"
          requiresWriteAccess
          variant="ghost"
          size="compact"
          onClick={onClear}
          disabled={busy || !items.length}
        >
          <Trash2 size={14} aria-hidden="true" />
          Svuota
        </Button>
      }
    >
      <ProbeLibraryGroups items={items} serverNames={serverNames}>
        {(groupItems) => (
          <ProbeQueueGroups items={groupItems} busy={busy} onRemove={onRemove} />
        )}
      </ProbeLibraryGroups>
    </ProbeList>
  );
}

function ProbeHistoryPanel({
  items,
  totalCount,
  serverNames,
  issuesOnly,
  hasIssues,
  busy,
  onIssuesOnly,
  onClear,
  onRetry,
  onRetryMany,
  retryProgress,
}: {
  items: ProbeHistoryItem[];
  totalCount: number;
  serverNames: Record<string, string>;
  issuesOnly: boolean;
  hasIssues: boolean;
  busy: boolean;
  onIssuesOnly: (value: boolean) => void;
  onClear: () => void;
  onRetry: (item: ProbeHistoryItem) => void;
  onRetryMany: () => void;
  retryProgress?: { completed: number; total: number } | null;
}) {
  return (
    <ProbeList
      icon={<History size={16} aria-hidden="true" />}
      title="Storico analisi"
      empty={
        issuesOnly && totalCount
          ? "Nessuna anomalia nello storico."
          : "Nessuna operazione registrata."
      }
      isEmpty={!items.length}
      actions={
        <>
          <label className="probe-list-filter">
            <input
              type="checkbox"
              checked={issuesOnly}
              onChange={(event) => onIssuesOnly(event.target.checked)}
              disabled={busy}
            />
            Solo anomalie
          </label>
          <Button
            type="button"
            requiresWriteAccess
            variant="secondary"
            size="compact"
            onClick={onRetryMany}
            disabled={busy || !hasIssues}
            title={
              retryProgress
                ? `Elaborazione ${retryProgress.completed}/${retryProgress.total}`
                : "Riprova tutti gli elementi con errori o metadati incompleti"
            }
          >
            <RotateCcw
              size={14}
              className={retryProgress ? "animate-spin" : ""}
              aria-hidden="true"
            />
            Riprova anomalie
          </Button>
          <Button
            type="button"
            requiresWriteAccess
            variant="ghost"
            size="compact"
            onClick={onClear}
            disabled={busy || !totalCount}
            title="Svuota tutto lo storico, inclusi gli elementi nascosti dal filtro"
          >
            <Trash2 size={14} aria-hidden="true" />
            Svuota tutto
          </Button>
        </>
      }
    >
      <ProbeLibraryGroups items={items} serverNames={serverNames}>
        {(groupItems) => (
          <ProbeRecordList
            kind="history"
            items={groupItems as ProbeHistoryItem[]}
            busy={busy}
            onRetry={(item) => onRetry(item as ProbeHistoryItem)}
          />
        )}
      </ProbeLibraryGroups>
    </ProbeList>
  );
}

function ProbeBlacklistPanel({
  title,
  description,
  items,
  serverNames,
  type,
  busy,
  onClear,
  onRemove,
  onRetry,
}: {
  title: string;
  description: string;
  items: ProbeBlacklistItem[];
  serverNames: Record<string, string>;
  type: "error" | "incomplete";
  busy: boolean;
  onClear: (type: "error" | "incomplete") => void;
  onRemove: (type: "error" | "incomplete", item: ProbeBlacklistItem) => void;
  onRetry: (type: "error" | "incomplete", item: ProbeBlacklistItem) => void;
}) {
  return (
    <ProbeList
      icon={<ShieldAlert size={16} aria-hidden="true" />}
      title={title}
      description={description}
      empty="Nessun elemento da gestire."
      isEmpty={!items.length}
      actions={
        <Button
          type="button"
          requiresWriteAccess
          variant="secondary"
          size="compact"
          onClick={() => onClear(type)}
          disabled={busy || !items.length}
        >
          <Trash2 size={14} aria-hidden="true" />
          Svuota
        </Button>
      }
    >
      <ProbeLibraryGroups items={items} serverNames={serverNames}>
        {(groupItems) => (
          <ProbeRecordList
            kind={type}
            items={groupItems as ProbeBlacklistItem[]}
            busy={busy}
            onRetry={(item) => onRetry(type, item as ProbeBlacklistItem)}
            onRemove={(item) => onRemove(type, item)}
          />
        )}
      </ProbeLibraryGroups>
    </ProbeList>
  );
}

function ProbeList({
  icon,
  title,
  description,
  empty,
  isEmpty,
  actions,
  children,
}: {
  icon: ReactNode;
  title?: string;
  description?: string;
  empty: string;
  isEmpty: boolean;
  actions: ReactNode;
  children: ReactNode;
}) {
  return (
    <div className="probe-list">
      <header>
        <div>
          {icon}
          <span>
            <h3>{title || "Elementi"}</h3>
            {description ? <p>{description}</p> : null}
          </span>
        </div>
        <div>{actions}</div>
      </header>
      {isEmpty ? <p>{empty}</p> : <div className="probe-list-rows">{children}</div>}
    </div>
  );
}

export { ProbeBlacklistPanel, ProbeHistoryPanel, ProbeQueuePanel };
