import type { KeyboardEvent } from "react";

import { tabAtKey } from "@/components/ui/tab-navigation";

type LatestView = "publications" | "telegram";

const latestViews: Array<{ id: LatestView; label: string }> = [
  { id: "publications", label: "Ultime pubblicazioni" },
  { id: "telegram", label: "Notifiche Telegram" },
];

function LatestViewTabs({
  activeView,
  onChange,
}: {
  activeView: LatestView;
  onChange: (view: LatestView) => void;
}) {
  function selectFromKeyboard(
    event: KeyboardEvent<HTMLButtonElement>,
    current: LatestView,
  ) {
    const next = tabAtKey(
      latestViews.map((view) => view.id),
      current,
      event.key,
    ) as LatestView | null;
    if (!next) return;

    event.preventDefault();
    onChange(next);
    window.requestAnimationFrame(() => {
      document.getElementById(`latest-view-tab-${next}`)?.focus();
    });
  }

  return (
    <div
      className="workspace-tabs workspace-tabs--section latest-view-tabs"
      role="tablist"
      aria-label="Visualizzazione pubblicazioni"
    >
      {latestViews.map((view) => {
        const active = view.id === activeView;
        return (
          <button
            key={view.id}
            id={`latest-view-tab-${view.id}`}
            type="button"
            role="tab"
            aria-selected={active}
            aria-controls={`latest-view-panel-${view.id}`}
            tabIndex={active ? 0 : -1}
            className={active ? "is-active" : undefined}
            onClick={() => onChange(view.id)}
            onKeyDown={(event) => selectFromKeyboard(event, view.id)}
          >
            {view.label}
          </button>
        );
      })}
    </div>
  );
}

export { LatestViewTabs };
export type { LatestView };
