import type { ReactNode } from "react";

import { WorkspaceRouteTabLayout } from "@/features/navigation/components/workspace-route-tab-layout";
import type { SecondaryNavigationMode } from "@/features/navigation/navigation-preferences";
import { researchNavigation } from "@/features/navigation/secondary-navigation";
import type { ResearchTab } from "@/features/research/research-navigation";

function ResearchTabs({
  active,
  children,
  variant = "tabs",
}: {
  active: ResearchTab;
  children: ReactNode;
  variant?: SecondaryNavigationMode;
}) {
  return (
    <WorkspaceRouteTabLayout
      activeId={active}
        ariaLabel="Sezioni ricerca"
        layoutClassName="research-tabs-layout"
        orderPage="research"
        tabs={researchNavigation}
      tabsClassName={`research-tabs research-tabs--${variant}`}
    >
      {children}
    </WorkspaceRouteTabLayout>
  );
}

export { ResearchTabs };
