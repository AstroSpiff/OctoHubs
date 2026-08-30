type PersistedTab<T extends string> = {
  id: T;
  label: string;
  legacyIds?: readonly string[];
};

type PersistedTabOrderEntry = {
  tab_key: string;
  position: number;
};

function normalizeTabOrder<T extends string>(
  tabs: readonly PersistedTab<T>[],
  entries: readonly PersistedTabOrderEntry[] | undefined,
): T[] {
  const tabByStoredId = new Map<string, T>();
  for (const tab of tabs) {
    tabByStoredId.set(tab.id, tab.id);
    for (const legacyId of tab.legacyIds || []) tabByStoredId.set(legacyId, tab.id);
  }

  const knownIds = new Set<T>();
  const orderedIds: T[] = [];
  for (const entry of [...(entries || [])].sort((left, right) => left.position - right.position)) {
    const tabId = tabByStoredId.get(entry.tab_key);
    if (tabId && !knownIds.has(tabId)) {
      knownIds.add(tabId);
      orderedIds.push(tabId);
    }
  }

  for (const tab of tabs) {
    if (!knownIds.has(tab.id)) orderedIds.push(tab.id);
  }
  return orderedIds;
}

function moveTab<T extends string>(order: readonly T[], tabId: T, direction: -1 | 1): T[] {
  const index = order.indexOf(tabId);
  const nextIndex = index + direction;
  if (index < 0 || nextIndex < 0 || nextIndex >= order.length) return [...order];

  const nextOrder = [...order];
  [nextOrder[index], nextOrder[nextIndex]] = [nextOrder[nextIndex], nextOrder[index]];
  return nextOrder;
}

function moveTabBefore<T extends string>(order: readonly T[], tabId: T, beforeTabId: T): T[] {
  const fromIndex = order.indexOf(tabId);
  const beforeIndex = order.indexOf(beforeTabId);
  if (fromIndex < 0 || beforeIndex < 0 || fromIndex === beforeIndex) return [...order];

  const nextOrder = [...order];
  nextOrder.splice(fromIndex, 1);
  nextOrder.splice(nextOrder.indexOf(beforeTabId), 0, tabId);
  return nextOrder;
}

function moveTabAfter<T extends string>(order: readonly T[], tabId: T, afterTabId: T): T[] {
  const fromIndex = order.indexOf(tabId);
  const afterIndex = order.indexOf(afterTabId);
  if (fromIndex < 0 || afterIndex < 0 || fromIndex === afterIndex) return [...order];

  const nextOrder = [...order];
  nextOrder.splice(fromIndex, 1);
  nextOrder.splice(nextOrder.indexOf(afterTabId) + 1, 0, tabId);
  return nextOrder;
}

function serializeTabOrder<T extends string>(page: string, order: readonly T[]) {
  return {
    page,
    order: order.map((tab_key, position) => ({ tab_key, position })),
  };
}

export { moveTab, moveTabAfter, moveTabBefore, normalizeTabOrder, serializeTabOrder };
export type { PersistedTab, PersistedTabOrderEntry };
