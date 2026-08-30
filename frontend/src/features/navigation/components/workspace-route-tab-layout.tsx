import type { ReactNode } from "react";

import { WorkspaceTabLayout, WorkspaceTabPanel } from "@/components/ui/workspace-layout";
import { WorkspaceRouteTabs } from "@/features/navigation/components/workspace-route-tabs";
import type { WorkspaceRouteTab } from "@/features/navigation/components/workspace-route-tabs";

type WorkspaceRouteTabLayoutProps<Id extends string> = {
  activeId: Id | null;
  ariaLabel: string;
  children: ReactNode;
  enabled?: boolean;
  layoutClassName?: string;
  orderPage: string;
  tabs: readonly WorkspaceRouteTab<Id>[];
  tabsClassName?: string;
};

function WorkspaceRouteTabLayout<Id extends string>({
  activeId,
  ariaLabel,
  children,
  enabled,
  layoutClassName,
  orderPage,
  tabs,
  tabsClassName,
}: WorkspaceRouteTabLayoutProps<Id>) {
  return (
    <WorkspaceTabLayout className={layoutClassName}>
      <WorkspaceRouteTabs
        activeId={activeId}
        ariaLabel={ariaLabel}
        className={tabsClassName}
        enabled={enabled}
        orderPage={orderPage}
        tabs={tabs}
      />
      <WorkspaceTabPanel>{children}</WorkspaceTabPanel>
    </WorkspaceTabLayout>
  );
}

export { WorkspaceRouteTabLayout };
