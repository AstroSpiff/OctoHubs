import { cva } from "class-variance-authority";

export const buttonVariants = cva(
  "inline-flex min-h-8 items-center justify-center gap-1.5 rounded-[var(--radius-control)] border px-2.5 text-[13px] font-semibold transition-colors focus-visible:outline-[3px] focus-visible:outline-[var(--color-focus)] focus-visible:outline-offset-2 disabled:pointer-events-none disabled:opacity-50",
  {
    variants: {
      variant: {
        primary: "border-[var(--color-accent)] bg-[var(--color-accent)] text-[var(--color-on-accent)] hover:border-[var(--color-accent-strong)] hover:bg-[var(--color-accent-strong)]",
        secondary: "border-[var(--color-border)] bg-[var(--color-surface-raised)] text-[var(--color-ink)] hover:bg-[var(--color-surface-muted)]",
        ghost: "border-transparent bg-transparent text-[var(--color-ink)] hover:bg-[var(--color-surface-muted)]",
        danger: "border-[var(--color-danger)] bg-[var(--color-danger)] text-[var(--color-on-danger)] hover:border-[var(--color-danger-strong)] hover:bg-[var(--color-danger-strong)]",
      },
      size: {
        default: "h-[var(--control-height)]",
        compact: "h-[var(--control-height-compact)] px-2.5 text-xs",
        icon: "h-[var(--control-height-compact)] w-[var(--control-height-compact)] px-0",
      },
    },
    defaultVariants: { variant: "secondary", size: "default" },
  },
);
