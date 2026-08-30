import type { DragEvent, KeyboardEvent } from "react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { getTabOrder, saveTabOrder } from "@/features/navigation/tab-order-api";
import { moveTab, moveTabAfter, moveTabBefore, normalizeTabOrder, serializeTabOrder } from "@/features/navigation/tab-order";
import type { PersistedTab } from "@/features/navigation/tab-order";

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

type NavigationOrderChangedDetail = {
  page: string;
  order: string[];
};

function usePersistedTabOrder<T extends string>({ page, tabs, enabled = true }: { page: string; tabs: readonly PersistedTab<T>[]; enabled?: boolean }) {
  const defaultOrder = normalizeTabOrder(tabs, []);
  const tabSignature = tabs.map((tab) => `${tab.id}:${(tab.legacyIds || []).join(",")}`).join("|");
  const [order, setOrder] = useState<T[]>(defaultOrder);
  const [draggingId, setDraggingId] = useState<T | null>(null);
  const [announcement, setAnnouncement] = useState("");
  const orderRef = useRef(order);
  const draggingIdRef = useRef<T | null>(null);
  const dragStartOrderRef = useRef<T[] | null>(null);
  const hasLocalOrderRef = useRef(false);
  const saveQueueRef = useRef<Promise<void>>(Promise.resolve());
  const tabsRef = useRef(tabs);
  tabsRef.current = tabs;
  const tabById = useMemo(() => new Map(tabs.map((tab) => [tab.id, tab])), [tabs]);

  const applyOrder = useCallback((nextOrder: T[]) => {
    orderRef.current = nextOrder;
    setOrder(nextOrder);
  }, []);

  const applyAndBroadcastOrder = useCallback((nextOrder: T[]) => {
    hasLocalOrderRef.current = true;
    navigationOrderCache.set(page, [...nextOrder]);
    applyOrder(nextOrder);
    if (typeof window === "undefined") return;
    window.dispatchEvent(new CustomEvent<NavigationOrderChangedDetail>(navigationOrderChangedEvent, {
      detail: { page, order: [...nextOrder] },
    }));
  }, [applyOrder, page]);

  useEffect(() => {
    if (!enabled) return;
    let disposed = false;
    hasLocalOrderRef.current = false;
    if (navigationOrderCache.has(page)) {
      const cachedOrder = navigationOrderCache.get(page) || [];
      applyOrder(normalizeTabOrder(tabsRef.current, cachedOrder.map((tab_key, position) => ({ tab_key, position }))));
      return;
    }
    const fallbackOrder = normalizeTabOrder(tabsRef.current, []);
    applyOrder(fallbackOrder);

    void getTabOrder(page)
      .then((entries) => {
        if (!disposed && !hasLocalOrderRef.current) {
          const loadedOrder = normalizeTabOrder(tabsRef.current, entries);
          navigationOrderCache.set(page, [...loadedOrder]);
          applyOrder(loadedOrder);
        }
      })
      .catch(() => {
        // A saved preference must never prevent navigation when storage is unavailable.
      });

    return () => {
      disposed = true;
    };
  }, [applyOrder, enabled, page, tabSignature]);

  useEffect(() => {
    if (!enabled || typeof window === "undefined") return;
    const onOrderChanged = (event: Event) => {
      const detail = (event as CustomEvent<NavigationOrderChangedDetail>).detail;
      if (!detail || detail.page !== page || !Array.isArray(detail.order)) return;
      hasLocalOrderRef.current = true;
      navigationOrderCache.set(page, [...detail.order]);
      const entries = detail.order.map((tab_key, position) => ({ tab_key, position }));
      applyOrder(normalizeTabOrder(tabsRef.current, entries));
    };
    window.addEventListener(navigationOrderChangedEvent, onOrderChanged);
    return () => window.removeEventListener(navigationOrderChangedEvent, onOrderChanged);
  }, [applyOrder, enabled, page, tabSignature]);

  const persist = useCallback((requestedOrder = orderRef.current) => {
    const orderAtSave = [...requestedOrder];
    const save = async () => {
      try {
        const response = await saveTabOrder(page, serializeTabOrder(page, orderAtSave).order);
        if (Array.isArray(response.order) && orderRef.current.join("|") === orderAtSave.join("|")) {
          applyAndBroadcastOrder(normalizeTabOrder(tabsRef.current, response.order));
        }
        setAnnouncement("Ordine delle schede salvato.");
      } catch {
        setAnnouncement("Impossibile salvare l'ordine delle schede.");
      }
    };

    const queuedSave = saveQueueRef.current.catch(() => undefined).then(save);
    saveQueueRef.current = queuedSave;
    return queuedSave;
  }, [applyAndBroadcastOrder, page]);

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

export { usePersistedTabOrder };
export type { TabOrderInteraction, TabOrderInteractionOptions };
