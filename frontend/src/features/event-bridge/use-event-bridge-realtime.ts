import { isEventBridgeUpdate } from "@/lib/application-events";
import { useApplicationEventRefresh } from "@/lib/use-application-event";

function useEventBridgeRealtime(onUpdate: () => void) {
  useApplicationEventRefresh(isEventBridgeUpdate, onUpdate);
}

export { isEventBridgeUpdate, useEventBridgeRealtime };
