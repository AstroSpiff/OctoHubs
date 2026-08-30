import { ChevronRight } from "@/components/ui/icons";
import type { ReactNode } from "react";

import {
  groupProbeItemsByLibrary,
  type ProbeListItem,
} from "@/features/probe/probe-grouping";

function ProbeLibraryGroups({
  items,
  serverNames,
  children,
}: {
  items: ProbeListItem[];
  serverNames: Record<string, string>;
  children: (items: ProbeListItem[]) => ReactNode;
}) {
  const groups = groupProbeItemsByLibrary(items, serverNames);

  return (
    <div className="probe-library-groups">
      {groups.map((group) => (
        <details key={group.id} className="probe-library-group">
          <summary>
            <span>
              <ChevronRight size={16} aria-hidden="true" />
              {group.label}
            </span>
            <strong>
              {group.items.length}{" "}
              {group.items.length === 1 ? "elemento" : "elementi"}
            </strong>
          </summary>
          <div className="probe-library-group-content">
            {children(group.items)}
          </div>
        </details>
      ))}
    </div>
  );
}

export { ProbeLibraryGroups };
