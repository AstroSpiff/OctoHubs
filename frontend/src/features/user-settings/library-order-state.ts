function normalizeLibraryOrder(value: unknown): string[] {
  return Array.isArray(value)
    ? value.map(String).filter(Boolean)
    : [];
}

function moveLibraryOrderItem(
  order: string[],
  index: number,
  offset: -1 | 1,
): string[] {
  const targetIndex = index + offset;
  if (targetIndex < 0 || targetIndex >= order.length) return order;
  const next = [...order];
  [next[index], next[targetIndex]] = [next[targetIndex], next[index]];
  return next;
}

function removeLibraryOrderItem(order: string[], index: number): string[] {
  return order.filter((_, itemIndex) => itemIndex !== index);
}

export {
  moveLibraryOrderItem,
  normalizeLibraryOrder,
  removeLibraryOrderItem,
};
