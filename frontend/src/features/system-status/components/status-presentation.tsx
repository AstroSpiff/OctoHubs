import { ExternalLink, RefreshCw, ServerCrash } from "@/components/ui/icons";
import type { ReactNode } from "react";
import { Link } from "react-router-dom";

import { Button } from "@/components/ui/button";
import { StatusBadge } from "@/components/ui/badge";
import { WorkspaceHeading } from "@/components/ui/workspace-heading";
import type { SystemItem, SystemSection } from "@/features/system-status/types";
import { cn } from "@/lib/utils";
import {
  severityIcon,
  severityLabel,
  formatSystemStatusMetric,
  formatSystemStatusTime,
  systemStatusHref,
  systemStatusRouterTarget,
} from "@/features/system-status/presentation";

function StatusItem({
  item,
  headingLevel,
}: {
  item: SystemItem;
  headingLevel: "h3" | "h4";
}) {
  const Heading = headingLevel;
  return (
    <article className={cn("status-item", `status-item--${item.severity}`)}>
      <div className="status-item-heading">
        <span className="status-item-icon">{severityIcon(item.severity)}</span>
        <Heading>{item.label}</Heading>
        <StatusBadge severity={item.severity}>
          {item.status_label || severityLabel(item.severity)}
        </StatusBadge>
      </div>
      <p className="status-item-summary">{item.summary}</p>
      {item.detail ? <p className="status-item-detail">{item.detail}</p> : null}
      {item.metrics.length ? (
        <dl className="status-metrics">
          {item.metrics.map((metric) => (
            <div key={`${item.id}-${metric.label}`}>
              <dt>{metric.label}</dt>
              <dd>{formatSystemStatusMetric(metric.value)}</dd>
            </div>
          ))}
        </dl>
      ) : null}
      {item.href ? (
        <SystemStatusLink className="detail-link" href={item.href}>
          Apri dettaglio <ExternalLink size={14} aria-hidden="true" />
        </SystemStatusLink>
      ) : null}
    </article>
  );
}

function SystemStatusSection({
  section,
  onRefresh,
  refreshing,
      error = "",
  headingLevel = "section",
}: {
  section: SystemSection;
  onRefresh: (checkServices?: boolean) => void;
  refreshing: boolean;
  error?: string;
  headingLevel?: "section" | "subsection";
}) {
  const timestamp = section.checked_at || section.updated_at;
  const itemHeadingLevel = headingLevel === "section" ? "h3" : "h4";
  return (
    <section
      className={cn("status-section", `status-section--${section.severity}`)}
      aria-labelledby={`section-${section.id}`}
      aria-busy={refreshing}
    >
      <WorkspaceHeading
        className="status-section-heading"
        level={headingLevel}
        leading={<span className="status-section-icon">{severityIcon(section.severity)}</span>}
        title={section.title}
        titleId={`section-${section.id}`}
        description={timestamp ? `Aggiornato ${formatSystemStatusTime(timestamp)}` : undefined}
        actions={<div className="section-actions">
          <StatusBadge severity={section.severity}>
            {section.status_label || severityLabel(section.severity)}
          </StatusBadge>
          <Button
            type="button"
            variant="ghost"
            size="compact"
            onClick={() => onRefresh(false)}
            disabled={refreshing}
          >
            <RefreshCw
              className={cn(refreshing && "animate-spin")}
              size={15}
              aria-hidden="true"
            />
            Aggiorna area
          </Button>
          {section.check_label ? (
            <Button
              type="button"
              variant="secondary"
              size="compact"
              requiresWriteAccess
              onClick={() => onRefresh(true)}
              disabled={refreshing}
            >
              <ServerCrash size={15} aria-hidden="true" />
              {section.check_label}
            </Button>
          ) : null}
          {section.href ? (
            <Button
              asChild
              type="button"
              variant="ghost"
              size="icon"
              title={`Apri ${section.title}`}
              aria-label={`Apri ${section.title}`}
            >
              <SystemStatusLink href={section.href}>
                <ExternalLink size={16} aria-hidden="true" />
              </SystemStatusLink>
            </Button>
          ) : null}
        </div>}
      />
      {error ? (
        <p className="status-section-error" role="alert">
          {error}
        </p>
      ) : null}
      <div className="status-items">
        {section.items.map((item) => (
          <StatusItem key={item.id} item={item} headingLevel={itemHeadingLevel} />
        ))}
      </div>
    </section>
  );
}

function SystemStatusLink({
  href,
  className,
  children,
}: {
  href: string;
  className?: string;
  children: ReactNode;
}) {
  const target = systemStatusHref(href);
  const routerTarget = systemStatusRouterTarget(href);
  if (routerTarget)
    return (
      <Link className={className} to={routerTarget}>
        {children}
      </Link>
    );
  return (
    <a className={className} href={target}>
      {children}
    </a>
  );
}

export { SystemStatusSection };
