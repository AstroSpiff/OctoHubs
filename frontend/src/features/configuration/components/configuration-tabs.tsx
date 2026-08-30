import type { ReactNode } from "react";

import { WorkspaceRouteTabLayout } from "@/features/navigation/components/workspace-route-tab-layout";
import type { ConfigurationTabId } from "@/features/configuration/configuration-navigation";
import type { SecondaryNavigationMode } from "@/features/navigation/navigation-preferences";
import { configurationNavigation } from "@/features/navigation/secondary-navigation";

function ConfigurationTabs({
  active,
  children,
  variant = "tabs",
}: {
  active: ConfigurationTabId;
  children: ReactNode;
  variant?: SecondaryNavigationMode;
}) {
  return (
    <WorkspaceRouteTabLayout
      activeId={active}
        ariaLabel="Sezioni configurazione"
        layoutClassName={`configuration-tabs-layout--${variant}`}
        orderPage="config"
        tabs={configurationNavigation}
      tabsClassName={`configuration-tabs configuration-tabs--${variant}`}
    >
      {children}
    </WorkspaceRouteTabLayout>
  );
}

export { ConfigurationTabs };
export type { ConfigurationTabId };
