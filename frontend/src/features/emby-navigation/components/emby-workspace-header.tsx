import { useLocation } from "react-router-dom";

import { EmbyWorkspaceTabs } from "@/features/emby-navigation/components/emby-workspace-tabs";
import type { SecondaryNavigationMode } from "@/features/navigation/navigation-preferences";
import { embyWorkspaceNavigation } from "@/features/navigation/secondary-navigation";
import { WorkspaceHeading } from "@/components/ui/workspace-heading";
import { WorkspaceSection } from "@/components/ui/workspace-layout";

function EmbyWorkspaceHeader({ variant }: { variant: SecondaryNavigationMode }) {
  const { pathname } = useLocation();
  const isWorkspaceRoute = embyWorkspaceNavigation.some(
    ({ to }) => pathname === to || pathname.startsWith(`${to}/`),
  );

  if (!isWorkspaceRoute) return null;

  return (
    <WorkspaceSection className={`page-layout emby-workspace-header emby-workspace-header--${variant}`} aria-labelledby="emby-workspace-title">
      <WorkspaceHeading
        className="emby-workspace-heading"
        context="Gestione Emby"
        title="Emby Toolkit"
        titleId="emby-workspace-title"
        description="Operazioni, monitoraggio, protezione della riproduzione, librerie, pubblicazioni e utenti dei server Emby."
      />
      <EmbyWorkspaceTabs variant={variant} />
    </WorkspaceSection>
  );
}

export { EmbyWorkspaceHeader };
