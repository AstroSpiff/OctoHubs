import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import {
  getConfigurationSettings,
  getTelegramSettings,
  runTelegramAction,
  saveConfigurationAutomations,
  saveConfigurationServices,
} from "@/features/configuration/api";
import type {
  ConfigurationAutomations,
  ServiceSettingsInput,
  TelegramAction,
} from "@/features/configuration/types";
import { useConfigurationRealtime } from "@/features/configuration/use-configuration-realtime";
import { useSensitiveMutation } from "@/lib/use-sensitive-mutation";

function useConfigurationSettings() {
  const client = useQueryClient();
  useConfigurationRealtime();
  const settings = useQuery({
    queryKey: ["configuration", "settings"],
    queryFn: getConfigurationSettings,
    refetchInterval: 15_000,
    refetchIntervalInBackground: false,
  });
  const telegram = useQuery({
    queryKey: ["configuration", "telegram"],
    queryFn: getTelegramSettings,
  });
  const saveAutomations = useMutation({
    mutationFn: (automations: ConfigurationAutomations) => saveConfigurationAutomations(automations),
    onSuccess: (payload) => client.setQueryData(["configuration", "settings"], payload),
  });
  const telegramAction = useSensitiveMutation({
    mutationFn: (action: TelegramAction) => runTelegramAction(action),
    onSuccess: (payload) => client.setQueryData(["configuration", "telegram"], payload),
  });
  const saveServices = useSensitiveMutation({
    mutationFn: (services: ServiceSettingsInput) => saveConfigurationServices(services),
    onSuccess: (payload) => client.setQueryData(["configuration", "settings"], payload),
  });

  return { settings, telegram, saveAutomations, saveServices, telegramAction };
}

export { useConfigurationSettings };
