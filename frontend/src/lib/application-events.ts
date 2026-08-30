import type { ApplicationEvent } from "@/lib/use-application-event";

const eventBridgeUpdatedMessage = "OctoHubsEventBridgeUpdated";
const configurationUpdatedMessage = "OctoHubsConfigurationUpdated";
const configurationScopes = ["servers", "telegram", "automations", "services"] as const;

type ConfigurationUpdateScope = typeof configurationScopes[number];

function isEventBridgeUpdate(event: ApplicationEvent): boolean {
  return event.MessageType === eventBridgeUpdatedMessage;
}

function configurationUpdateScope(
  event: ApplicationEvent,
): ConfigurationUpdateScope | null {
  if (event.MessageType !== configurationUpdatedMessage) return null;
  const data = event.Data;
  if (!data || typeof data !== "object") return null;
  const scope = (data as { scope?: unknown }).scope;
  return typeof scope === "string" && configurationScopes.includes(scope as ConfigurationUpdateScope)
    ? scope as ConfigurationUpdateScope
    : null;
}

export {
  configurationUpdatedMessage,
  configurationUpdateScope,
  eventBridgeUpdatedMessage,
  isEventBridgeUpdate,
};
export type { ConfigurationUpdateScope };
