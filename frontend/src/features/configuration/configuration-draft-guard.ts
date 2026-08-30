import type { ConfigurationTabId } from "@/features/configuration/configuration-navigation";

function configurationTabHasDraft(tab: ConfigurationTabId) {
  return tab === "servers" || tab === "telegram" || tab === "automations" || tab === "services" || tab === "event-bridge";
}

export { configurationTabHasDraft };
