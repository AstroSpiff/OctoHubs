import type { ConfigurationTabId } from "@/features/configuration/configuration-navigation";
import type { ProbeScope } from "@/features/probe/types";
import type { ResearchTab } from "@/features/research/research-navigation";
import { configurationPath } from "@/features/configuration/configuration-navigation";
import { probePath } from "@/features/probe/probe-navigation";
import { researchPath } from "@/features/research/research-navigation";

type SecondaryNavigationItem<Id extends string = string> = {
  id: Id;
  label: string;
  to: string;
  legacyIds?: readonly string[];
};

const embyWorkspaceNavigation = [
  { id: "emby-live", to: "/emby-live", label: "Emby Live", legacyIds: ["operations", "actions"] },
  { id: "transcode-guard", to: "/transcode-guard", label: "Transcode Guard" },
  { id: "stream-stats", to: "/stream-stats", label: "Statistiche stream", legacyIds: ["transcode-stats"] },
  { id: "libraries", to: "/libraries", label: "Librerie" },
  { id: "latest", to: "/latest", label: "Pubblicazioni" },
  { id: "users", to: "/users", label: "Utenti" },
] as const satisfies ReadonlyArray<SecondaryNavigationItem>;

const configurationNavigation = [
  { id: "system-status", to: configurationPath("system-status"), label: "Stato sistema" },
  { id: "servers", to: configurationPath("servers"), label: "Server Emby", legacyIds: ["emby-servers"] },
  { id: "telegram", to: configurationPath("telegram"), label: "Telegram" },
  { id: "automations", to: configurationPath("automations"), label: "Automazioni" },
  { id: "services", to: configurationPath("services"), label: "Servizi" },
  { id: "event-bridge", to: configurationPath("event-bridge"), label: "Event Bridge" },
  { id: "accounts", to: configurationPath("accounts"), label: "Accessi OctoHubs" },
] as const satisfies ReadonlyArray<SecondaryNavigationItem<ConfigurationTabId>>;

const researchNavigation = [
  { id: "independent", to: researchPath("independent"), label: "Ricerca indipendente", legacyIds: ["independent-search"] },
  { id: "summary", to: researchPath("summary"), label: "Ricerche e riepilogo", legacyIds: ["scan"] },
  { id: "rules", to: researchPath("rules"), label: "Regole di ricerca" },
  { id: "requests", to: researchPath("requests"), label: "Richieste monitorate" },
] as const satisfies ReadonlyArray<SecondaryNavigationItem<ResearchTab>>;

const probeNavigation = [
  { id: "recent", to: probePath("recent"), label: "Ultimi aggiunti" },
  { id: "libraries", to: probePath("libraries"), label: "Librerie" },
] as const satisfies ReadonlyArray<SecondaryNavigationItem<ProbeScope>>;

function isSecondaryNavigationItemActive(
  item: SecondaryNavigationItem,
  pathname: string,
  hash: string,
) {
  const [itemPath, itemHash] = item.to.split("#");
  if (itemHash) return pathname === itemPath && hash === `#${itemHash}`;
  return pathname === itemPath || pathname.startsWith(`${itemPath}/`);
}

export {
  configurationNavigation,
  embyWorkspaceNavigation,
  isSecondaryNavigationItemActive,
  probeNavigation,
  researchNavigation,
};
export type { SecondaryNavigationItem };
