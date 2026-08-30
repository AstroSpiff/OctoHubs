function isTopmostDialog<T>(
  dialogs: readonly T[],
  current: T | null,
): boolean {
  return current !== null && dialogs.at(-1) === current;
}

export { isTopmostDialog };
