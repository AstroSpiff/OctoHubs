import { useRef, useState } from "react";

import type { ConfirmationOptions } from "@/components/ui/confirmation-dialog";
import { retryProbeItem } from "@/features/probe/api";
import { probeBulkActionNotice } from "@/features/probe/probe-bulk-action";
import { probeScopeLabel } from "@/features/probe/presentation";
import type {
  ProbeBlacklistItem,
  ProbeHistoryItem,
  ProbeScope,
} from "@/features/probe/types";
import type { useProbeScopeData } from "@/features/probe/use-probe";

type ProbeScopeData = Pick<
  ReturnType<typeof useProbeScopeData>,
  | "clearHistory"
  | "refresh"
  | "removeBlacklist"
  | "removeQueue"
  | "retry"
  | "retryBlacklisted"
>;

type ProbeDataActionItem = Pick<
  ProbeHistoryItem | ProbeBlacklistItem,
  "server_id" | "item_id" | "media_source_id"
>;

type ProbeNotice = { message: string; tone: "success" | "warning" };
type ProbeBulkProgress = { label: string; completed: number; total: number };

function useProbeDataActions({
  scope,
  targetIds,
  data,
  confirm,
}: {
  scope: ProbeScope;
  targetIds: string[];
  data: ProbeScopeData;
  confirm: (options: ConfirmationOptions) => Promise<boolean>;
}) {
  const [retryProgress, setRetryProgress] = useState<{
    completed: number;
    total: number;
  } | null>(null);
  const [retrySummary, setRetrySummary] = useState<ProbeNotice | null>(null);
  const [bulkProgress, setBulkProgress] = useState<ProbeBulkProgress | null>(null);
  const [bulkSummary, setBulkSummary] = useState<ProbeNotice | null>(null);
  const bulkActionRunning = useRef(false);

  async function runForEveryServer(
    label: string,
    action: (serverId: string) => Promise<unknown>,
  ) {
    if (bulkActionRunning.current) return;
    const serverIds = [...targetIds];
    if (!serverIds.length) {
      setBulkSummary(probeBulkActionNotice(label, 0, 0));
      return;
    }

    bulkActionRunning.current = true;
    setBulkSummary(null);
    setBulkProgress({ label, completed: 0, total: serverIds.length });
    let succeeded = 0;

    for (const [index, serverId] of serverIds.entries()) {
      try {
        await action(serverId);
        succeeded += 1;
      } catch {
        // L'errore specifico resta disponibile anche nell'alert della pagina.
      }
      setBulkProgress({ label, completed: index + 1, total: serverIds.length });
    }

    bulkActionRunning.current = false;
    setBulkProgress(null);
    await data.refresh();
    setBulkSummary(probeBulkActionNotice(label, succeeded, serverIds.length));
  }

  async function clearQueue() {
    if (
      !(await confirm({
        title: "Svuota coda",
        description: `Svuotare la coda ${probeScopeLabel(scope).toLowerCase()}?`,
        confirmLabel: "Svuota coda",
        tone: "danger",
      }))
    ) {
      return;
    }

    await runForEveryServer("Coda", (serverId) =>
      data.removeQueue.mutateAsync({ serverId, scope }),
    );
  }

  async function clearHistory() {
    if (
      !(await confirm({
        title: "Svuota storico",
        description: `Svuotare lo storico ${probeScopeLabel(scope).toLowerCase()}?`,
        confirmLabel: "Svuota storico",
        tone: "danger",
      }))
    ) {
      return;
    }

    await runForEveryServer("Storico", (serverId) =>
      data.clearHistory.mutateAsync({ serverId, scope }),
    );
  }

  async function clearBlacklist(type: "error" | "incomplete") {
    if (
      !(await confirm({
        title: "Svuota elenco",
        description:
          "Svuotare questo elenco? Gli elementi potranno essere elaborati di nuovo.",
        confirmLabel: "Svuota elenco",
        tone: "danger",
      }))
    ) {
      return;
    }

    await runForEveryServer(
      type === "error" ? "Elenco errori" : "Elenco metadati incompleti",
      (serverId) => data.removeBlacklist.mutateAsync({ serverId, scope, type }),
    );
  }

  async function removeQueueItem(item: ProbeDataActionItem) {
    if (!item.server_id) return;
    if (
      !(await confirm({
        title: "Rimuovi dalla coda",
        description: "Rimuovere questo elemento dalla coda di analisi?",
        confirmLabel: "Rimuovi elemento",
        tone: "danger",
      }))
    ) {
      return;
    }

    data.removeQueue.mutate({
      serverId: item.server_id,
      scope,
      itemId: item.item_id,
      mediaSourceId: item.media_source_id,
    });
  }

  async function removeBlacklistItem(
    type: "error" | "incomplete",
    item: ProbeDataActionItem,
  ) {
    if (!item.server_id) return;
    if (
      !(await confirm({
        title: "Rimuovi dall'elenco",
        description:
          "Rimuovere questo elemento dall'elenco delle anomalie? Tornerà elaborabile dal workflow.",
        confirmLabel: "Rimuovi elemento",
        tone: "danger",
      }))
    ) {
      return;
    }

    data.removeBlacklist.mutate({
      serverId: item.server_id,
      scope,
      type,
      itemId: item.item_id,
      mediaSourceId: item.media_source_id,
    });
  }

  function retryHistoryItem(item: ProbeDataActionItem) {
    if (!item.server_id) return;
    data.retry.mutate({
      serverId: item.server_id,
      scope,
      itemId: item.item_id,
      mediaSourceId: item.media_source_id,
    });
  }

  function retryBlacklistItem(
    type: "error" | "incomplete",
    item: ProbeDataActionItem,
  ) {
    if (!item.server_id) return;
    data.retryBlacklisted.mutate({
      serverId: item.server_id,
      scope,
      type,
      itemId: item.item_id,
      mediaSourceId: item.media_source_id,
    });
  }

  async function retryMany(items: ProbeDataActionItem[]) {
    const retryItems = items.flatMap((item) =>
      item.server_id
        ? [
            {
              serverId: item.server_id,
              scope,
              itemId: item.item_id,
              mediaSourceId: item.media_source_id,
            },
          ]
        : [],
    );
    if (!retryItems.length) {
      setRetrySummary({
        message: "Nessuna anomalia associata a un server disponibile.",
        tone: "warning",
      });
      return;
    }
    if (
      !(await confirm({
        title: "Riprova elementi",
        description: `Riprova ${retryItems.length} ${retryItems.length === 1 ? "elemento" : "elementi"} con errori o metadati incompleti?`,
        confirmLabel: "Avvia nuovo tentativo",
      }))
    ) {
      return;
    }

    let queued = 0;
    let failed = 0;
    setRetrySummary(null);
    setRetryProgress({ completed: 0, total: retryItems.length });
    for (const [index, item] of retryItems.entries()) {
      try {
        await retryProbeItem(item);
        queued += 1;
      } catch {
        failed += 1;
      }
      setRetryProgress({ completed: index + 1, total: retryItems.length });
    }
    setRetryProgress(null);
    await data.refresh();
    setRetrySummary({
      message: failed
        ? `Nuovo tentativo completato: ${queued} in coda, ${failed} non elaborati.`
        : `Nuovo tentativo completato: ${queued} ${queued === 1 ? "elemento aggiunto" : "elementi aggiunti"} alla coda.`,
      tone: failed ? "warning" : "success",
    });
  }

  return {
    clearBlacklist,
    clearHistory,
    clearQueue,
    bulkProgress,
    bulkSummary,
    isRunningBulkAction: bulkProgress !== null,
    isRetryingMany: retryProgress !== null,
    removeBlacklistItem,
    removeQueueItem,
    retryBlacklistItem,
    retryHistoryItem,
    retryMany,
    retryProgress,
    retrySummary,
  };
}

export { useProbeDataActions };
