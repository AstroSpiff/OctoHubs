import type { ComponentPropsWithoutRef } from "react";

import { cn } from "@/lib/utils";

function WorkspacePage({ className, ...props }: ComponentPropsWithoutRef<"div">) {
  return <div className={cn("page-layout", "workspace-page", className)} {...props} />;
}

function WorkspaceSection({ className, ...props }: ComponentPropsWithoutRef<"section">) {
  return <section className={cn("workspace-section", className)} {...props} />;
}

function WorkspaceTabLayout({ className, ...props }: ComponentPropsWithoutRef<"section">) {
  return <section className={cn("workspace-tab-layout", className)} {...props} />;
}

function WorkspaceTabPanel({ className, ...props }: ComponentPropsWithoutRef<"div">) {
  return <div className={cn("workspace-tab-panel", className)} {...props} />;
}

export { WorkspacePage, WorkspaceSection, WorkspaceTabLayout, WorkspaceTabPanel };
