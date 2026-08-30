import {
  FlaskConical,
  FolderKanban,
  MonitorCog,
  Search,
  Settings2,
  type IconComponent,
} from "@/components/ui/icons";

import {
  configurationNavigation,
  embyWorkspaceNavigation,
  probeNavigation,
  researchNavigation,
  type SecondaryNavigationItem,
} from "@/features/navigation/secondary-navigation";

type PrimaryNavigationItem = {
  id: string;
  to: string;
  matchPath?: string;
  label: string;
  shortLabel: string;
  icon: IconComponent;
  workspace?: boolean;
  secondary?: readonly SecondaryNavigationItem[];
  secondaryOrderPage?: string;
};

const primaryNavigation: PrimaryNavigationItem[] = [
  { id: "research", to: "/research/independent", matchPath: "/research", label: "Ricerca", shortLabel: "Ricerca", icon: Search, secondary: researchNavigation, secondaryOrderPage: "research" },
  {
    id: "emby",
    to: "/emby-live",
    label: "Emby Toolkit",
    shortLabel: "Emby",
    icon: MonitorCog,
    workspace: true,
    secondary: embyWorkspaceNavigation,
    secondaryOrderPage: "emby",
  },
  { id: "collections", to: "/collections", label: "Collezioni", shortLabel: "Collezioni", icon: FolderKanban },
  { id: "probe", to: "/probe/recent", matchPath: "/probe", label: "Media Probe", shortLabel: "Probe", icon: FlaskConical, secondary: probeNavigation, secondaryOrderPage: "emby-probe" },
  {
    id: "configuration",
    to: "/configuration/system-status",
    matchPath: "/configuration",
    label: "Configurazione",
    shortLabel: "Config.",
    icon: Settings2,
    secondary: configurationNavigation,
    secondaryOrderPage: "config",
  },
];

function isPrimaryNavigationItemActive(item: PrimaryNavigationItem, pathname: string): boolean {
  const matchPath = item.matchPath || item.to;
  const directMatch = pathname === matchPath || pathname.startsWith(`${matchPath}/`);
  if (directMatch) return true;
  if (!item.workspace) return false;
  return embyWorkspaceNavigation.some(({ to }) => pathname === to || pathname.startsWith(`${to}/`));
}

export { isPrimaryNavigationItemActive, primaryNavigation };
export type { PrimaryNavigationItem };
