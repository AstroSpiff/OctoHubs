import { cva } from "class-variance-authority";

export const buttonVariants = cva(
  "app-button inline-flex items-center justify-center gap-1 whitespace-normal rounded-[var(--radius-control)] border px-2 text-center font-semibold leading-[1.1] transition-colors focus-visible:outline-[3px] focus-visible:outline-[var(--color-focus)] focus-visible:outline-offset-2 disabled:pointer-events-none disabled:opacity-50",
  {
    variants: {
      variant: {
        primary: "border-[var(--color-accent)] bg-[var(--color-accent)] text-[var(--color-on-accent)] hover:border-[var(--color-accent-strong)] hover:bg-[var(--color-accent-strong)]",
        secondary: "border-[var(--color-border)] bg-[var(--color-surface-raised)] text-[var(--color-ink)] hover:bg-[var(--color-surface-muted)]",
        ghost: "border-transparent bg-transparent text-[var(--color-ink)] hover:bg-[var(--color-surface-muted)]",
        danger: "border-[var(--color-danger)] bg-[var(--color-danger)] text-[var(--color-on-danger)] hover:border-[var(--color-danger-strong)] hover:bg-[var(--color-danger-strong)]",
      },
      size: {
        default: "app-button--text app-button--default min-h-[var(--control-height)] py-1",
        compact: "app-button--text app-button--compact min-h-[var(--control-height-compact)] py-1",
        icon: "app-button--icon h-[var(--control-height-compact)] w-[var(--control-height-compact)] min-h-0 shrink-0 whitespace-nowrap px-0 py-0",
      },
    },
    defaultVariants: { variant: "secondary", size: "default" },
  },
);
