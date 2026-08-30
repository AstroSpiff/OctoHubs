import { useCallback } from "react";
import { useQueryClient } from "@tanstack/react-query";

import { configurationUpdateScope } from "@/lib/application-events";
import { useApplicationEventRefresh } from "@/lib/use-application-event";

function useConfigurationRealtime() {
  const client = useQueryClient();
  const refresh = useCallback((event: Parameters<typeof configurationUpdateScope>[0]) => {
    const scope = configurationUpdateScope(event);
    if (scope === "servers") {
      void client.invalidateQueries({ queryKey: ["configuration", "emby-servers"] });
      return;
    }
    if (scope === "telegram") {
      void client.invalidateQueries({ queryKey: ["configuration", "telegram"] });
      return;
    }
    if (scope === "automations" || scope === "services") {
      void client.invalidateQueries({ queryKey: ["configuration", "settings"] });
    }
  }, [client]);

  useApplicationEventRefresh(
    (event) => configurationUpdateScope(event) !== null,
    refresh,
  );
}

export { useConfigurationRealtime };
