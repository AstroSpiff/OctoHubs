function safeCollectionProviderLink(value: string | undefined, sourceType: string) {
  if (!value) return "";
  const allowedHosts: Record<string, Set<string>> = {
    mdblist: new Set(["mdblist.com", "www.mdblist.com"]),
    trakt: new Set(["trakt.tv", "www.trakt.tv"]),
  };
  const normalizedSource = sourceType.trim().toLowerCase();
  const provider = normalizedSource.startsWith("trakt")
    ? "trakt"
    : normalizedSource.startsWith("mdblist")
      ? "mdblist"
      : normalizedSource;
  const hosts = allowedHosts[provider];
  if (!hosts) return "";
  try {
    const url = new URL(value);
    if (url.protocol !== "https:" || !hosts.has(url.hostname.toLowerCase())) return "";
    url.username = "";
    url.password = "";
    url.search = "";
    url.hash = "";
    return url.toString();
  } catch {
    return "";
  }
}

export { safeCollectionProviderLink };
