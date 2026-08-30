import { useLocation } from "react-router-dom";

import { WorkspaceRouteTabs } from "@/features/navigation/components/workspace-route-tabs";
import type { SecondaryNavigationMode } from "@/features/navigation/navigation-preferences";
import { embyWorkspaceNavigation } from "@/features/navigation/secondary-navigation";

const workspaceTabs = embyWorkspaceNavigation;

function EmbyWorkspaceTabs({ variant = "tabs" }: { variant?: SecondaryNavigationMode }) {
  const { pathname } = useLocation();
  const activeTab = workspaceTabs.find(
    ({ to }) => pathname === to || pathname.startsWith(`${to}/`),
  )?.id || null;

  return (
    <WorkspaceRouteTabs
      activeId={activeTab}
      ariaLabel="Sezioni Emby"
      className={`emby-workspace-tabs emby-workspace-tabs--${variant}`}
      enabled={Boolean(activeTab)}
      orderPage="emby"
      tabs={workspaceTabs}
    />
  );
}

export { EmbyWorkspaceTabs };
