import type { DragEvent, KeyboardEvent } from "react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { getTabOrder, saveTabOrder } from "@/features/navigation/tab-order-api";
import { moveTab, moveTabAfter, moveTabBefore, normalizeTabOrder, serializeTabOrder } from "@/features/navigation/tab-order";
import type { PersistedTab } from "@/features/navigation/tab-order";
import {
  SessionOwnerChangedError,
  assertAuthenticatedActionOwner,
  captureAuthenticatedActionOwner,
} from "@/lib/http";

type TabOrderInteraction = {
  draggable: true;
  onDragStart: (event: DragEvent<HTMLElement>) => void;
  onDragOver: (event: DragEvent<HTMLElement>) => void;
  onDrop: (event: DragEvent<HTMLElement>) => void;
  onDragEnd: () => void;
  onKeyDown: (event: KeyboardEvent<HTMLElement>) => boolean;
};

type TabOrderInteractionOptions = {
  dropAxis?: "horizontal" | "vertical";
};

const navigationOrderChangedEvent = "octohubs:navigation-order-changed";
const navigationOrderCache = new Map<string, string[]>();
const navigationConfirmedOrderCache = new Map<string, string[]>();
const navigationSaveQueues = new Map<string, Promise<void>>();

type NavigationOrderChangedDetail = {
  ownerKey: string;
  page: string;
  order: string[];
};

function usePersistedTabOrder<T extends string>({ accountId = null, page, tabs, enabled = true }: { accountId?: number | null; page: string; tabs: readonly PersistedTab<T>[]; enabled?: boolean }) {
  const defaultOrder = normalizeTabOrder(tabs, []);
  const ownerKey = `${accountId ?? "anonymous"}:${page}`;
  const tabSignature = tabs.map((tab) => `${tab.id}:${(tab.legacyIds || []).join(",")}`).join("|");
  const [ownedOrder, setOwnedOrder] = useState<{ ownerKey: string; order: T[] }>(() => ({ ownerKey, order: defaultOrder }));
  const order = ownedOrder.ownerKey === ownerKey
    ? ownedOrder.order
    : normalizeTabOrder(tabs, (navigationOrderCache.get(ownerKey) || []).map((tab_key, position) => ({ tab_key, position })));
  const [draggingId, setDraggingId] = useState<T | null>(null);
  const [announcement, setAnnouncement] = useState("");
  const orderRef = useRef(order);
  orderRef.current = order;
  const ownerKeyRef = useRef(ownerKey);
  ownerKeyRef.current = ownerKey;
  const draggingIdRef = useRef<T | null>(null);
  const dragStartOrderRef = useRef<T[] | null>(null);
  const confirmedOrderRef = useRef<T[]>(defaultOrder);
  const hasLocalOrderRef = useRef(false);
  const tabsRef = useRef(tabs);
  tabsRef.current = tabs;
  const tabById = useMemo(() => new Map(tabs.map((tab) => [tab.id, tab])), [tabs]);

  const applyOrder = useCallback((nextOrder: T[]) => {
    orderRef.current = nextOrder;
    setOwnedOrder({ ownerKey: ownerKeyRef.current, order: nextOrder });
  }, []);

  const applyAndBroadcastOrder = useCallback((nextOrder: T[]) => {
    hasLocalOrderRef.current = true;
    navigationOrderCache.set(ownerKey, [...nextOrder]);
    applyOrder(nextOrder);
    if (typeof window === "undefined") return;
    window.dispatchEvent(new CustomEvent<NavigationOrderChangedDetail>(navigationOrderChangedEvent, {
      detail: { ownerKey, page, order: [...nextOrder] },
    }));
  }, [applyOrder, ownerKey, page]);

  useEffect(() => {
    if (!enabled) return;
    let disposed = false;
    hasLocalOrderRef.current = false;
    if (navigationOrderCache.has(ownerKey)) {
      const cachedOrder = navigationOrderCache.get(ownerKey) || [];
      applyOrder(normalizeTabOrder(tabsRef.current, cachedOrder.map((tab_key, position) => ({ tab_key, position }))));
      const confirmedOrder = navigationConfirmedOrderCache.get(ownerKey)
        || normalizeTabOrder(tabsRef.current, []);
      confirmedOrderRef.current = normalizeTabOrder(
        tabsRef.current,
        confirmedOrder.map((tab_key, position) => ({ tab_key, position })),
      );
      return;
    }
    const fallbackOrder = normalizeTabOrder(tabsRef.current, []);
    confirmedOrderRef.current = fallbackOrder;
    applyOrder(fallbackOrder);

    void getTabOrder(page)
      .then((entries) => {
        if (!disposed && !hasLocalOrderRef.current) {
          const loadedOrder = normalizeTabOrder(tabsRef.current, entries);
          navigationOrderCache.set(ownerKey, [...loadedOrder]);
          navigationConfirmedOrderCache.set(ownerKey, [...loadedOrder]);
          confirmedOrderRef.current = loadedOrder;
          applyOrder(loadedOrder);
        }
      })
      .catch(() => {
        // A saved preference must never prevent navigation when storage is unavailable.
      });

    return () => {
      disposed = true;
    };
  }, [applyOrder, enabled, ownerKey, page, tabSignature]);

  useEffect(() => {
    if (!enabled || typeof window === "undefined") return;
    const onOrderChanged = (event: Event) => {
      const detail = (event as CustomEvent<NavigationOrderChangedDetail>).detail;
      if (!detail || detail.ownerKey !== ownerKey || detail.page !== page || !Array.isArray(detail.order)) return;
      hasLocalOrderRef.current = true;
      navigationOrderCache.set(ownerKey, [...detail.order]);
      const entries = detail.order.map((tab_key, position) => ({ tab_key, position }));
      applyOrder(normalizeTabOrder(tabsRef.current, entries));
    };
    window.addEventListener(navigationOrderChangedEvent, onOrderChanged);
    return () => window.removeEventListener(navigationOrderChangedEvent, onOrderChanged);
  }, [applyOrder, enabled, ownerKey, page, tabSignature]);

  const persist = useCallback((requestedOrder = orderRef.current) => {
    const orderAtSave = [...requestedOrder];
    const owner = captureAuthenticatedActionOwner();
    const ownerKeyAtSave = ownerKey;
    const save = async () => {
      try {
        assertAuthenticatedActionOwner(owner);
        if (ownerKeyRef.current !== ownerKeyAtSave) return;
        const response = await saveTabOrder(page, serializeTabOrder(page, orderAtSave).order);
        assertAuthenticatedActionOwner(owner);
        if (ownerKeyRef.current !== ownerKeyAtSave) return;
        const confirmedOrder = Array.isArray(response.order)
          ? normalizeTabOrder(tabsRef.current, response.order)
          : orderAtSave;
        navigationConfirmedOrderCache.set(ownerKeyAtSave, [...confirmedOrder]);
        confirmedOrderRef.current = confirmedOrder;
        if (Array.isArray(response.order) && orderRef.current.join("|") === orderAtSave.join("|")) {
          applyAndBroadcastOrder(confirmedOrder);
        }
        setAnnouncement("Ordine delle schede salvato.");
      } catch (reason) {
        if (reason instanceof SessionOwnerChangedError || ownerKeyRef.current !== ownerKeyAtSave) return;
        if (orderRef.current.join("|") === orderAtSave.join("|")) {
          const sharedConfirmedOrder = navigationConfirmedOrderCache.get(ownerKeyAtSave)
            || confirmedOrderRef.current;
          const normalizedSharedConfirmedOrder = normalizeTabOrder(
            tabsRef.current,
            sharedConfirmedOrder.map((tab_key, position) => ({ tab_key, position })),
          );
          confirmedOrderRef.current = normalizedSharedConfirmedOrder;
          applyAndBroadcastOrder(normalizedSharedConfirmedOrder);
        }
        setAnnouncement("Impossibile salvare l'ordine delle schede.");
      }
    };

    return enqueueNavigationSave(ownerKeyAtSave, save);
  }, [applyAndBroadcastOrder, ownerKey, page]);

  const finishDrag = useCallback(() => {
    const startedWith = dragStartOrderRef.current;
    const draggedId = draggingIdRef.current;
    dragStartOrderRef.current = null;
    draggingIdRef.current = null;
    setDraggingId(null);

    if (!startedWith || startedWith.join("|") === orderRef.current.join("|")) return;
    const label = draggedId ? tabById.get(draggedId)?.label || draggedId : "Scheda";
    setAnnouncement(`${label} riordinata.`);
    void persist([...orderRef.current]);
  }, [persist, tabById]);

  const move = useCallback((tabId: T, direction: -1 | 1) => {
    const nextOrder = moveTab(orderRef.current, tabId, direction);
    if (nextOrder.join("|") === orderRef.current.join("|")) return false;
    applyAndBroadcastOrder(nextOrder);
    const label = tabById.get(tabId)?.label || tabId;
    setAnnouncement(`${label} spostata ${direction < 0 ? "a sinistra" : "a destra"}.`);
    void persist();
    return true;
  }, [applyAndBroadcastOrder, persist, tabById]);

  const interaction = useCallback((tabId: T, options: TabOrderInteractionOptions = {}): TabOrderInteraction => ({
    draggable: true,
    onDragStart: (event) => {
      event.dataTransfer.effectAllowed = "move";
      event.dataTransfer.setData("text/plain", tabId);
      dragStartOrderRef.current = [...orderRef.current];
      draggingIdRef.current = tabId;
      setDraggingId(tabId);
    },
    onDragOver: (event) => {
      const currentDraggingId = draggingIdRef.current;
      if (!currentDraggingId || currentDraggingId === tabId) return;
      event.preventDefault();
      event.dataTransfer.dropEffect = "move";
      const rect = event.currentTarget.getBoundingClientRect();
      const dropAxis = options.dropAxis || "horizontal";
      const insertAfter = dropAxis === "vertical"
        ? event.clientY >= rect.top + rect.height / 2
        : event.clientX >= rect.left + rect.width / 2;
      const nextOrder = insertAfter
        ? moveTabAfter(orderRef.current, currentDraggingId, tabId)
        : moveTabBefore(orderRef.current, currentDraggingId, tabId);
      if (nextOrder.join("|") !== orderRef.current.join("|")) applyAndBroadcastOrder(nextOrder);
    },
    onDrop: (event) => {
      event.preventDefault();
      const currentDraggingId = draggingIdRef.current;
      if (!currentDraggingId) return;
      const rect = event.currentTarget.getBoundingClientRect();
      const dropAxis = options.dropAxis || "horizontal";
      const insertAfter = dropAxis === "vertical"
        ? event.clientY >= rect.top + rect.height / 2
        : event.clientX >= rect.left + rect.width / 2;
      const nextOrder = insertAfter
        ? moveTabAfter(orderRef.current, currentDraggingId, tabId)
        : moveTabBefore(orderRef.current, currentDraggingId, tabId);
      if (nextOrder.join("|") !== orderRef.current.join("|")) applyAndBroadcastOrder(nextOrder);
      finishDrag();
    },
    onDragEnd: finishDrag,
    onKeyDown: (event) => {
      if (!event.altKey || (event.key !== "ArrowLeft" && event.key !== "ArrowRight")) return false;
      event.preventDefault();
      return move(tabId, event.key === "ArrowLeft" ? -1 : 1);
    },
  }), [applyAndBroadcastOrder, finishDrag, move]);

  return { announcement, draggingId, interaction, move, order };
}

function enqueueNavigationSave(page: string, save: () => Promise<void>) {
  const previous = navigationSaveQueues.get(page) || Promise.resolve();
  const queued = previous.catch(() => undefined).then(save);
  navigationSaveQueues.set(page, queued);
  const clearQueue = () => {
    if (navigationSaveQueues.get(page) === queued) navigationSaveQueues.delete(page);
  };
  void queued.then(clearQueue, clearQueue);
  return queued;
}

export { usePersistedTabOrder };
export type { TabOrderInteraction, TabOrderInteractionOptions };
