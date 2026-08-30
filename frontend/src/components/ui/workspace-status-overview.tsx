import type { CSSProperties, ComponentPropsWithoutRef, ReactNode } from "react";

import { Card } from "@/components/ui/card";
import { cn } from "@/lib/utils";

type WorkspaceStatusOverviewMetric = {
  label: ReactNode;
  tone?: "error" | "info" | "ok" | "warning" | "neutral";
  value: ReactNode;
};

type WorkspaceStatusOverviewProps = Omit<
  ComponentPropsWithoutRef<"section">,
  "children"
> & {
  columns?: number;
  description: ReactNode;
  icon: ReactNode;
  iconTone: "error" | "info" | "ok" | "warning" | "neutral";
  metrics: readonly WorkspaceStatusOverviewMetric[];
  status?: ReactNode;
  title: ReactNode;
};

function WorkspaceStatusOverview({
  className,
  columns,
  description,
  icon,
  iconTone,
  metrics,
  status,
  style,
  title,
  ...props
}: WorkspaceStatusOverviewProps) {
  return (
    <Card
      className={cn("workspace-status-overview", className)}
      style={{
        ...style,
        "--workspace-status-overview-columns": columns || metrics.length,
      } as CSSProperties}
      {...props}
    >
      <div className="workspace-status-overview-primary">
        <span className={cn("workspace-status-overview-icon", `is-${iconTone}`)}>
          {icon}
        </span>
        <div className="workspace-status-overview-copy">
          <strong>{title}</strong>
          <small>{description}</small>
        </div>
        {status ? <div className="workspace-status-overview-status">{status}</div> : null}
      </div>
      <dl className="workspace-status-overview-metrics">
        {metrics.map(({ label, tone = "neutral", value }, index) => (
          <div className={`is-${tone}`} key={typeof label === "string" ? label : index}>
            <dt>{label}</dt>
            <dd>{value}</dd>
          </div>
        ))}
      </dl>
    </Card>
  );
}

export { WorkspaceStatusOverview };
export type { WorkspaceStatusOverviewMetric };
