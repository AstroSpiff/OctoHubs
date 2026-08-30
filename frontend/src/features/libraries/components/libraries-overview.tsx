import { FolderTree, LibraryBig, MonitorUp, PlayCircle } from "@/components/ui/icons";

import { WorkspaceMetricGrid } from "@/components/ui/workspace-metric-grid";
import { libraryOverview } from "@/features/libraries/presentation";
import type { LibraryGroup } from "@/features/libraries/types";

function LibrariesOverview({ groups, activeJobs }: { groups: LibraryGroup[]; activeJobs: number }) {
  const overview = libraryOverview(groups);
  const items = [
    { label: "Gruppi", value: overview.groups, icon: FolderTree, tone: "neutral" },
    { label: "Librerie", value: overview.libraries, icon: LibraryBig, tone: "neutral" },
    { label: "Server", value: overview.servers, icon: MonitorUp, tone: "ok" },
    { label: "Scansioni attive", value: activeJobs, icon: PlayCircle, tone: activeJobs ? "warning" : "neutral" },
  ] as const;
  return <WorkspaceMetricGrid className="libraries-overview" metrics={items.map(({ icon: Icon, ...item }) => ({ ...item, icon: <Icon size={17} aria-hidden="true" /> }))} />;
}

export { LibrariesOverview };
