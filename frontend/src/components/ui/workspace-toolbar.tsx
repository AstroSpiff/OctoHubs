import type { ComponentPropsWithoutRef, ReactNode } from "react";

import { cn } from "@/lib/utils";

type WorkspaceToolbarGroupProps = ComponentPropsWithoutRef<"div"> & {
  label: ReactNode;
};

type WorkspaceToolbarFieldProps = ComponentPropsWithoutRef<"label"> & {
  label: ReactNode;
};

function WorkspaceToolbar({ className, ...props }: ComponentPropsWithoutRef<"section">) {
  return <section className={cn("workspace-toolbar", className)} {...props} />;
}

function WorkspaceToolbarRow({ className, ...props }: ComponentPropsWithoutRef<"div">) {
  return <div className={cn("workspace-toolbar-row", className)} {...props} />;
}

function WorkspaceToolbarActions({ className, ...props }: ComponentPropsWithoutRef<"div">) {
  return <div className={cn("workspace-toolbar-actions", className)} {...props} />;
}

function WorkspaceToolbarGroup({ children, className, label, ...props }: WorkspaceToolbarGroupProps) {
  return (
    <div className={cn("workspace-toolbar-group", className)} {...props}>
      <p className="workspace-toolbar-label">{label}</p>
      <div className="workspace-toolbar-group-content">{children}</div>
    </div>
  );
}

function WorkspaceToolbarField({ children, className, label, ...props }: WorkspaceToolbarFieldProps) {
  return (
    <label className={cn("workspace-toolbar-field", className)} {...props}>
      <span className="workspace-toolbar-label">{label}</span>
      {children}
    </label>
  );
}

export {
  WorkspaceToolbar,
  WorkspaceToolbarActions,
  WorkspaceToolbarField,
  WorkspaceToolbarGroup,
  WorkspaceToolbarRow,
};
