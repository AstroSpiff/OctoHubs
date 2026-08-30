import { LoaderCircle } from "@/components/ui/icons";

import { latestRefreshPresentation } from "@/features/emby-latest/latest-progress-presentation";
import type { LatestProgress } from "@/features/emby-latest/types";

function LatestRefreshProgress({ progress }: { progress?: LatestProgress }) {
  const view = latestRefreshPresentation(progress?.progress);
  const progressLabel =
    view.completed !== undefined && view.total !== undefined
      ? `${view.completed} / ${view.total}`
      : "In corso";

  return (
    <section className="latest-refresh-progress" aria-live="polite">
      <div>
        <span>
          <LoaderCircle className="animate-spin" size={15} aria-hidden="true" />
          {view.label}
        </span>
        <strong>{view.percent === undefined ? progressLabel : `${view.percent}%`}</strong>
      </div>
      <div
        className="latest-refresh-progress-track"
        role="progressbar"
        aria-label={`Avanzamento ${view.label.toLowerCase()}`}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={view.percent}
      >
        <span style={{ width: `${view.percent ?? 18}%` }} />
      </div>
      <p>
        {view.message}
        {view.completed !== undefined && view.total !== undefined
          ? ` · ${progressLabel}`
          : ""}
      </p>
    </section>
  );
}

export { LatestRefreshProgress };
