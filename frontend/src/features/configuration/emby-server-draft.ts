import type {
  EmbyServerInput,
  EmbyServerSettings,
} from "@/features/configuration/types";

const emptyEmbyServerInput: EmbyServerInput = {
  alias: "",
  url: "",
  enabled: true,
  notes: "",
  icon: "fa-server",
  icon_color: "#3b82f6",
  icon_style: "solid",
};

function embyServerInputFromSettings(
  server?: EmbyServerSettings,
): EmbyServerInput {
  if (!server) return { ...emptyEmbyServerInput };
  return {
    alias: server.alias,
    url: server.url,
    enabled: server.enabled,
    notes: server.notes,
    icon: server.icon,
    icon_color: server.icon_color,
    icon_style: server.icon_style === "regular" ? "regular" : "solid",
  };
}

function sameEmbyServerInput(left: EmbyServerInput, right: EmbyServerInput) {
  return (
    left.alias === right.alias &&
    left.url === right.url &&
    left.enabled === right.enabled &&
    left.notes === right.notes &&
    left.icon === right.icon &&
    left.icon_color === right.icon_color &&
    left.icon_style === right.icon_style
  );
}

function refreshedEmbyServerDraft(
  draft: EmbyServerInput,
  previous: EmbyServerInput,
  incoming: EmbyServerInput,
) {
  return sameEmbyServerInput(draft, previous) ? incoming : draft;
}

export {
  embyServerInputFromSettings,
  refreshedEmbyServerDraft,
  sameEmbyServerInput,
};
