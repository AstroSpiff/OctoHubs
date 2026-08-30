import { request } from "@/lib/http";
import type {
  ConfigurationAutomations,
  ConfigurationSettingsPayload,
  EmbyServerInput,
  EmbyServerMutationPayload,
  EmbyServersPayload,
  TelegramAction,
  TelegramSettingsPayload,
  ConnectionCheckPayload,
  ServiceSettingsInput,
  TraktDevicePoll,
  TraktDeviceStart,
} from "@/features/configuration/types";

function getEmbyServers(): Promise<EmbyServersPayload> {
  return request<EmbyServersPayload>("/api/v1/emby/servers");
}

function createEmbyServer(input: EmbyServerInput): Promise<EmbyServerMutationPayload> {
  return request<EmbyServerMutationPayload>("/api/v1/emby/servers", { method: "POST", body: JSON.stringify(input) });
}

function updateEmbyServer(serverId: string, input: EmbyServerInput): Promise<EmbyServerMutationPayload> {
  return request<EmbyServerMutationPayload>(`/api/v1/emby/servers/${encodeURIComponent(serverId)}`, { method: "PUT", body: JSON.stringify(input) });
}

function deleteEmbyServer(serverId: string): Promise<{ success: boolean; message: string; cleanup_error?: string | null }> {
  return request<{ success: boolean; message: string; cleanup_error?: string | null }>(`/api/v1/emby/servers/${encodeURIComponent(serverId)}`, { method: "DELETE" });
}

function getConfigurationSettings(): Promise<ConfigurationSettingsPayload> {
  return request<ConfigurationSettingsPayload>("/api/v1/configuration/settings");
}

function saveConfigurationAutomations(automations: ConfigurationAutomations): Promise<ConfigurationSettingsPayload> {
  return request<ConfigurationSettingsPayload>("/api/v1/configuration/automations", {
    method: "PUT",
    body: JSON.stringify(automations),
  });
}

function saveConfigurationServices(services: ServiceSettingsInput): Promise<ConfigurationSettingsPayload> {
  return request<ConfigurationSettingsPayload>("/api/v1/configuration/services", {
    method: "PUT",
    body: JSON.stringify(services),
  });
}

function testConfigurationConnections(): Promise<ConnectionCheckPayload> {
  return request<ConnectionCheckPayload>("/api/v1/test-connections", { method: "POST" });
}

function startTraktDeviceFlow(clientId: string): Promise<TraktDeviceStart> {
  return request<TraktDeviceStart>("/api/v1/trakt/device/start", {
    method: "POST",
    body: JSON.stringify({ client_id: clientId }),
  });
}

function pollTraktDeviceFlow(clientId: string, clientSecret: string, deviceCode: string): Promise<TraktDevicePoll> {
  return request<TraktDevicePoll>("/api/v1/trakt/device/poll", {
    method: "POST",
    body: JSON.stringify({ client_id: clientId, client_secret: clientSecret, device_code: deviceCode }),
  });
}

function clearTraktDeviceFlow(): Promise<{ success: boolean; message: string }> {
  return request<{ success: boolean; message: string }>("/api/v1/trakt/clear", { method: "POST" });
}

function getTelegramSettings(): Promise<TelegramSettingsPayload> {
  return request<TelegramSettingsPayload>("/api/v1/telegram/settings");
}

function runTelegramAction(action: TelegramAction): Promise<TelegramSettingsPayload> {
  return request<TelegramSettingsPayload>("/api/v1/telegram/action", {
    method: "POST",
    body: JSON.stringify(action),
  });
}

export {
  createEmbyServer,
  clearTraktDeviceFlow,
  deleteEmbyServer,
  getConfigurationSettings,
  getEmbyServers,
  getTelegramSettings,
  runTelegramAction,
  saveConfigurationAutomations,
  saveConfigurationServices,
  startTraktDeviceFlow,
  testConfigurationConnections,
  pollTraktDeviceFlow,
  updateEmbyServer,
};
