import type { HTMLAttributes } from "react";

import { cn } from "@/lib/utils";

export type Severity = "ok" | "info" | "warning" | "error" | "neutral" | "unknown";

const severityClasses: Record<Severity, string> = {
  ok: "border-[var(--color-success-border)] bg-[var(--color-success-soft)] text-[var(--color-success-strong)]",
  info: "border-[var(--color-info-border)] bg-[var(--color-info-soft)] text-[var(--color-info)]",
  warning: "border-[var(--color-warning-border)] bg-[var(--color-warning-soft)] text-[var(--color-warning)]",
  error: "border-[var(--color-danger-border)] bg-[var(--color-danger-soft)] text-[var(--color-danger-strong)]",
  neutral: "border-[var(--color-border)] bg-[var(--color-surface-muted)] text-[var(--color-muted)]",
  unknown: "border-[var(--color-border)] bg-[var(--color-surface-muted)] text-[var(--color-muted)]",
};

function StatusBadge({ severity, className, children, ...props }: HTMLAttributes<HTMLSpanElement> & { severity: Severity }) {
  return (
    <span
      className={cn("inline-flex min-h-6 items-center rounded-[var(--radius-control)] border px-2 text-xs font-bold tracking-wide", severityClasses[severity], className)}
      {...props}
    >
      {children}
    </span>
  );
}

export { StatusBadge };
