const configurationTabs = ["system-status", "servers", "telegram", "automations", "services", "event-bridge", "accounts"] as const;

type ConfigurationTabId = typeof configurationTabs[number];

function configurationTabFromRoute(value: string | undefined): ConfigurationTabId {
  const candidate = value || "";
  return isConfigurationTabId(candidate) ? candidate : "system-status";
}

function configurationTabFromHash(hash: string): ConfigurationTabId {
  const value = hash.replace(/^#/, "").split("?", 1)[0].trim();
  if (value === "emby-servers") return "servers";
  return configurationTabFromRoute(value);
}

function configurationPath(tab: ConfigurationTabId): string {
  return `/configuration/${tab}`;
}

function configurationTabAtOffset(current: ConfigurationTabId, offset: number, order: readonly ConfigurationTabId[] = configurationTabs): ConfigurationTabId {
  const index = order.indexOf(current);
  return order[(index + offset + order.length) % order.length];
}

function isConfigurationTabId(value: string): value is ConfigurationTabId {
  return (configurationTabs as readonly string[]).includes(value);
}

export {
  configurationPath,
  configurationTabAtOffset,
  configurationTabFromHash,
  configurationTabFromRoute,
  configurationTabs,
};
export type { ConfigurationTabId };
