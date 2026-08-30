function tabAtKey<T extends string>(
  tabs: readonly T[],
  current: T,
  key: string,
): T | undefined {
  const currentIndex = tabs.indexOf(current);
  if (currentIndex < 0) return undefined;

  if (key === "Home") return tabs[0];
  if (key === "End") return tabs[tabs.length - 1];

  const offset =
    key === "ArrowLeft" || key === "ArrowUp"
      ? -1
      : key === "ArrowRight" || key === "ArrowDown"
        ? 1
        : 0;
  if (!offset) return undefined;
  return tabs[(currentIndex + offset + tabs.length) % tabs.length];
}

export { tabAtKey };
