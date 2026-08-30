import { CheckCircle2, CircleAlert, Layers3, Repeat2 } from "@/components/ui/icons";

import { WorkspaceMetricGrid } from "@/components/ui/workspace-metric-grid";
import { collectionCounts } from "@/features/collections/presentation";
import type { EmbyCollection } from "@/features/collections/types";

function CollectionsOverview({ collections }: { collections: EmbyCollection[] }) {
  const counts = collectionCounts(collections);
  const items = [
    { label: "Collezioni", value: counts.total, icon: Layers3, tone: "neutral" },
    { label: "Attive", value: counts.enabled, icon: CheckCircle2, tone: "ok" },
    { label: "Da verificare", value: counts.attention, icon: CircleAlert, tone: "warning" },
    { label: "Automatiche", value: counts.automated, icon: Repeat2, tone: "neutral" },
  ] as const;

  return <WorkspaceMetricGrid className="collections-overview" metrics={items.map(({ icon: Icon, ...item }) => ({ ...item, icon: <Icon size={17} aria-hidden="true" /> }))} />;
}

export { CollectionsOverview };
