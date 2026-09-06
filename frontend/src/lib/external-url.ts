function safeExternalHttpUrl(value: unknown): string | null {
  if (typeof value !== "string" || !value.trim() || value.length > 4096) return null;
  try {
    const parsed = new URL(value);
    if (!(["http:", "https:"] as string[]).includes(parsed.protocol)) return null;
    if (!parsed.hostname || parsed.username || parsed.password) return null;
    return parsed.href;
  } catch {
    return null;
  }
}

export { safeExternalHttpUrl };
