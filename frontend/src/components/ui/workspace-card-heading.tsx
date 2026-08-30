import type { ReactNode } from "react";

import { cn } from "@/lib/utils";

type WorkspaceCardHeadingProps = {
  actions?: ReactNode;
  className?: string;
  context?: string;
  count?: ReactNode;
  leading?: ReactNode;
  title: ReactNode;
  titleId?: string;
};

function WorkspaceCardHeading({
  actions,
  className,
  context,
  count,
  leading,
  title,
  titleId,
}: WorkspaceCardHeadingProps) {
  return (
    <header className={cn("workspace-card-heading", className)}>
      <div className="workspace-card-heading-main">
        {leading ? (
          <span className="workspace-card-heading-leading" aria-hidden="true">
            {leading}
          </span>
        ) : null}
        <h3
          id={titleId}
          title={context}
          className={context ? "contextual-heading" : undefined}
        >
          {title}
        </h3>
      </div>
      {count !== undefined || actions ? (
        <div className="workspace-card-heading-actions">
          {count !== undefined ? (
            <span className="workspace-card-heading-count">{count}</span>
          ) : null}
          {actions}
        </div>
      ) : null}
    </header>
  );
}

export { WorkspaceCardHeading };
