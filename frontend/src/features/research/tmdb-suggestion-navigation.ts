export function nextTmdbSuggestionIndex(
  current: number,
  direction: 1 | -1,
  total: number,
): number {
  if (!total) return -1;
  if (current < 0) return direction > 0 ? 0 : total - 1;
  return (current + direction + total) % total;
}
