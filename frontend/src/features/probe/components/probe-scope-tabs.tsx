import type { ReactNode } from "react";

import { WorkspaceRouteTabLayout } from "@/features/navigation/components/workspace-route-tab-layout";
import type { SecondaryNavigationMode } from "@/features/navigation/navigation-preferences";
import { probeNavigation } from "@/features/navigation/secondary-navigation";
import type { ProbeScope } from "@/features/probe/types";

function ProbeScopeTabs({
  children,
  value,
  variant = "tabs",
}: {
  children?: ReactNode;
  value: ProbeScope;
  variant?: SecondaryNavigationMode;
}) {
  return (
    <WorkspaceRouteTabLayout
      activeId={value}
      ariaLabel="Ambito Probe"
      layoutClassName="probe-tabs-layout"
      orderPage="emby-probe"
      tabs={probeNavigation}
      tabsClassName={`probe-scope-tabs probe-scope-tabs--${variant}`}
    >
      {children}
    </WorkspaceRouteTabLayout>
  );
}

export { ProbeScopeTabs };
