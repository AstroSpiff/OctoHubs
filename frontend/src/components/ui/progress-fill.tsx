import { cn } from "@/lib/utils";

function normalizedProgress(value: number, fallback = 0): number {
  const numeric = Number.isFinite(value) ? value : fallback;
  return Math.max(0, Math.min(100, numeric));
}

function ProgressFill({
  className,
  fallback = 0,
  value,
}: {
  className?: string;
  fallback?: number;
  value: number;
}) {
  return (
    <progress
      aria-hidden="true"
      className={cn("csp-progress-fill", className)}
      max={100}
      tabIndex={-1}
      value={normalizedProgress(value, fallback)}
    />
  );
}

export { ProgressFill };
