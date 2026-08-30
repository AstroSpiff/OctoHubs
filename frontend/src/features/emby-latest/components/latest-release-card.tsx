import { ChevronDown, Clock3, Film, Folder } from "@/components/ui/icons";
import { useId, useState } from "react";

import { EmbyServerIcon } from "@/features/emby-live/components/emby-server-icon";
import {
  changeDetails,
  changeTitle,
  formatLatestDate,
  formatRuntime,
} from "@/features/emby-latest/presentation";
import type { LatestItem } from "@/features/emby-latest/types";

function LatestReleaseCard({ item }: { item: LatestItem }) {
  const [expanded, setExpanded] = useState(false);
  const detailsId = useId();
  const rating = Number(item.community_rating);
  const badges = [
    item.server_name,
    item.library_name || item.library,
    item.update_label,
    item.jellyseerr_requested
      ? item.jellyseerr_request_status_label || "Richiesto"
      : "",
    item.item_type === "Series" ? "" : formatRuntime(item.runtime_minutes),
    item.child_count ? `Episodi ${item.child_count}` : "",
    Number.isFinite(rating) && rating > 0 ? `★ ${rating.toFixed(1)}` : "",
    item.official_rating,
    formatLatestDate(item.added_at || item.premiere_date)
      ? `Aggiunto ${formatLatestDate(item.added_at || item.premiere_date)}`
      : "",
  ].filter(Boolean);
  const changes = item.changes || [];

  return (
    <article className="latest-release-card">
      <div className="latest-release-poster">
        {item.image_url ? (
          <img src={item.image_url} alt="" loading="lazy" />
        ) : (
          <Film size={28} aria-hidden="true" />
        )}
      </div>
      <div className="latest-release-copy">
        <div className="latest-release-title-row">
          <strong>
            {item.title || "Titolo"}
            {item.year ? ` (${item.year})` : ""}
          </strong>
          {changes.length ? (
            <button
              type="button"
              className="latest-release-details-toggle"
              aria-expanded={expanded}
              aria-controls={detailsId}
              onClick={() => setExpanded((current) => !current)}
            >
              <ChevronDown size={14} aria-hidden="true" />
              {expanded ? "Nascondi" : "Dettagli"}
            </button>
          ) : null}
        </div>
        {badges.length ? (
          <div className="latest-release-badges">
            {badges.map((badge, index) => (
              <span key={`${badge}-${index}`}>
                {index === 0 ? (
                  <EmbyServerIcon
                    icon={item.server_icon}
                    iconStyle={item.server_icon_style}
                    color={item.server_icon_color}
                    size={11}
                  />
                ) : index === 1 ? (
                  <Folder size={11} aria-hidden="true" />
                ) : null}
                {badge}
              </span>
            ))}
          </div>
        ) : null}
        {item.genres?.length ? (
          <p className="latest-release-genres">{item.genres.join(" · ")}</p>
        ) : null}
        {item.overview ? (
          <p className="latest-release-overview">{item.overview}</p>
        ) : null}
        {changes.length && expanded ? (
          <div className="latest-release-changes" id={detailsId}>
            {changes.map((change, index) => (
              <div key={`${change.kind || "change"}-${index}`}>
                <strong>{changeTitle(change)}</strong>
                <span>{changeDetails(change)}</span>
              </div>
            ))}
          </div>
        ) : null}
      </div>
    </article>
  );
}

function LatestReleaseColumn({
  title,
  items,
  total,
  emptyText,
}: {
  title: string;
  items: LatestItem[];
  total: number;
  emptyText: string;
}) {
  return (
    <section className="latest-release-column">
      <header>
        <h3>{title}</h3>
        <span>
          {items.length}
          {total > items.length ? ` / ${total}` : ""}{" "}
          {total === 1 ? "elemento" : "elementi"}
        </span>
      </header>
      <div className="latest-release-list">
        {items.length ? (
          items.map((item, index) => (
            <LatestReleaseCard
              key={`${item.server_id || "server"}-${item.item_id || item.title || "item"}-${index}`}
              item={item}
            />
          ))
        ) : (
          <p className="latest-release-empty">
            <Clock3 size={17} aria-hidden="true" />
            {emptyText}
          </p>
        )}
      </div>
    </section>
  );
}

export { LatestReleaseCard, LatestReleaseColumn };
