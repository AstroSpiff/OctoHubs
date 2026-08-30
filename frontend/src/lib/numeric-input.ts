function boundedWholeNumberInput(
  value: string,
  minimum: number,
  maximum = Number.MAX_SAFE_INTEGER,
): number {
  const parsed = Number(value);
  if (!Number.isFinite(parsed)) return minimum;
  return Math.min(maximum, Math.max(minimum, Math.trunc(parsed)));
}

export { boundedWholeNumberInput };
