import type { ComponentPropsWithoutRef, ReactNode } from "react";

import { Card } from "@/components/ui/card";
import { cn } from "@/lib/utils";

type WorkspaceMetric = {
  icon: ReactNode;
  label: ReactNode;
  tone?: "error" | "info" | "ok" | "warning" | "neutral";
  value: ReactNode;
};

type WorkspaceMetricGridProps = Omit<ComponentPropsWithoutRef<"div">, "children"> & {
  metrics: readonly WorkspaceMetric[];
};

function WorkspaceMetricGrid({ className, metrics, ...props }: WorkspaceMetricGridProps) {
  return (
    <div className={cn("workspace-metric-grid", className)} {...props}>
      {metrics.map(({ icon, label, tone = "neutral", value }, index) => (
        <Card className="workspace-metric-card" key={typeof label === "string" ? label : index}>
          <span className={cn("workspace-metric-icon", `is-${tone}`)}>{icon}</span>
          <div>
            <p>{label}</p>
            <strong>{value}</strong>
          </div>
        </Card>
      ))}
    </div>
  );
}

export { WorkspaceMetricGrid };
export type { WorkspaceMetric };
