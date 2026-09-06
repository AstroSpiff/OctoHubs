import { GripVertical } from "@/components/ui/icons";
import { useEffect, useRef } from "react";
import { NavLink } from "react-router-dom";

import { cn } from "@/lib/utils";
import { usePersistedTabOrder } from "@/features/navigation/use-persisted-tab-order";
import type { PersistedTab } from "@/features/navigation/tab-order";
import { useWorkspaceCapabilities } from "@/features/session/workspace-capabilities-context";

type WorkspaceRouteTab<Id extends string> = PersistedTab<Id> & {
  to: string;
};

function WorkspaceRouteTabs<Id extends string>({
  activeId,
  ariaLabel,
  className,
  enabled = true,
  orderPage,
  tabs,
}: {
  activeId: Id | null;
  ariaLabel: string;
  className?: string;
  enabled?: boolean;
  orderPage: string;
  tabs: readonly WorkspaceRouteTab<Id>[];
}) {
  const { accountId } = useWorkspaceCapabilities();
  const tabOrder = usePersistedTabOrder({ accountId, page: orderPage, tabs, enabled });
  const activeTabRef = useRef<HTMLAnchorElement>(null);
  const tabOrderKey = tabOrder.order.join("|");
  const orderedTabs = tabOrder.order
    .map((id) => tabs.find((tab) => tab.id === id))
    .filter((tab): tab is WorkspaceRouteTab<Id> => Boolean(tab));

  useEffect(() => {
    activeTabRef.current?.scrollIntoView({ block: "nearest", inline: "center" });
  }, [activeId, tabOrderKey]);

  if (!enabled) return null;

  return (
    <nav className={cn("workspace-tabs", className)} aria-label={ariaLabel}>
      {orderedTabs.map((tab) => {
        const active = tab.id === activeId;
        return (
          <NavLink
            key={tab.id}
            ref={active ? activeTabRef : undefined}
            to={tab.to}
            aria-current={active ? "page" : undefined}
            className={cn("workspace-route-tab", active && "is-active", tabOrder.draggingId === tab.id && "is-dragging")}
            title="Trascina per riordinare"
            {...tabOrder.interaction(tab.id)}
          >
            <GripVertical className="tab-reorder-grip" size={14} aria-hidden="true" />
            {tab.label}
          </NavLink>
        );
      })}
      <span className="sr-only" aria-live="polite">{tabOrder.announcement}</span>
    </nav>
  );
}

export { WorkspaceRouteTabs };
export type { WorkspaceRouteTab };
