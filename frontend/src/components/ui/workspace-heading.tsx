import type { ReactNode } from "react";

import { cn } from "@/lib/utils";

type WorkspaceHeadingProps = {
  actions?: ReactNode;
  actionsClassName?: string;
  className?: string;
  context?: string;
  description?: ReactNode;
  leading?: ReactNode;
  level?: "page" | "section" | "subsection";
  title: ReactNode;
  titleId?: string;
};

function WorkspaceHeading({
  actions,
  actionsClassName,
  className,
  context,
  description,
  leading,
  level = "page",
  title,
  titleId,
}: WorkspaceHeadingProps) {
  const Title = level === "page" ? "h1" : level === "section" ? "h2" : "h3";

  return (
    <header className={cn("workspace-heading", `workspace-heading--${level}`, className)}>
      <div className="workspace-heading-main">
        {leading ? <div className="workspace-heading-leading">{leading}</div> : null}
        <div className="workspace-heading-copy">
          <Title
            id={titleId}
            className={context ? "workspace-heading-title-with-context" : undefined}
            title={context}
          >
            {title}
          </Title>
          {description ? <p className="workspace-heading-description">{description}</p> : null}
        </div>
      </div>
      {actions ? <div className={cn("workspace-heading-actions", actionsClassName)}>{actions}</div> : null}
    </header>
  );
}

export { WorkspaceHeading };
