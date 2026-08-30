import { Image, RefreshCw } from "@/components/ui/icons";
import { useEffect, useMemo, useState } from "react";

import { Button } from "@/components/ui/button";
import { WorkspaceChoiceGroup } from "@/components/ui/workspace-choice-group";
import {
  latestItemSelectionKey,
  reconcileLatestItemSelection,
} from "@/features/emby-latest/latest-item-selection";
import { latestPreviewItemLabel } from "@/features/emby-latest/presentation";
import type { LatestItem, LatestPreview } from "@/features/emby-latest/types";

const previewKinds = ["movie", "series"] as const;
type PreviewKind = (typeof previewKinds)[number];

function sanitizeTelegramHtml(value: string) {
  const root = document.createElement("template");
  root.innerHTML = value;
  const allowed = new Set([
    "B",
    "STRONG",
    "I",
    "EM",
    "U",
    "S",
    "CODE",
    "PRE",
    "A",
    "BR",
    "BLOCKQUOTE",
  ]);
  const elements = Array.from(root.content.querySelectorAll("*"));
  elements.forEach((element) => {
    if (!allowed.has(element.tagName)) {
      element.replaceWith(...Array.from(element.childNodes));
      return;
    }
    const href =
      element.tagName === "A" ? element.getAttribute("href") || "" : "";
    for (const attribute of Array.from(element.attributes))
      element.removeAttribute(attribute.name);
    if (element.tagName === "A" && /^https?:/i.test(href)) {
      element.setAttribute("href", href);
      element.setAttribute("target", "_blank");
      element.setAttribute("rel", "noopener noreferrer");
    }
  });
  return root.innerHTML;
}

function LatestNotificationPreview({
  template,
  movies,
  series,
  result,
  loading,
  onPreview,
}: {
  template: string;
  movies: LatestItem[];
  series: LatestItem[];
  result?: LatestPreview;
  loading: boolean;
  onPreview: (items: Partial<Record<"movie" | "series", LatestItem>>) => void;
}) {
  const [movieKey, setMovieKey] = useState("");
  const [seriesKey, setSeriesKey] = useState("");
  const [activeKind, setActiveKind] = useState<PreviewKind>("movie");
  const movie = useMemo(
    () =>
      movies.find(
        (item, index) =>
          latestItemSelectionKey(item, index) === movieKey,
      ),
    [movieKey, movies],
  );
  const show = useMemo(
    () =>
      series.find(
        (item, index) =>
          latestItemSelectionKey(item, index) === seriesKey,
      ),
    [seriesKey, series],
  );

  useEffect(() => {
    setMovieKey((current) => reconcileLatestItemSelection(movies, current));
  }, [movies]);
  useEffect(() => {
    setSeriesKey((current) => reconcileLatestItemSelection(series, current));
  }, [series]);

  useEffect(() => {
    if (!template.trim() || (!movie && !show)) return;
    const timeout = window.setTimeout(
      () => onPreview({ movie, series: show }),
      500,
    );
    return () => window.clearTimeout(timeout);
  }, [movie, onPreview, show, template]);

  function refreshPreview() {
    if (template.trim()) onPreview({ movie, series: show });
  }

  return (
    <section className="latest-config-card latest-preview-panel">
      <header>
        <h4>Anteprima notifiche</h4>
        <p>
          Scegli contenuti reali per controllare testo, formattazione e
          immagine.
        </p>
      </header>
      <div className="latest-preview-selects">
        <label>
          Film anteprima
          <select
            value={movieKey}
            onChange={(event) => setMovieKey(event.target.value)}
          >
            <option value="">Nessun film</option>
            {movies.map((item, index) => {
              const key = latestItemSelectionKey(item, index);
              return (
                <option key={key} value={key}>
                  {latestPreviewItemLabel(item)}
                </option>
              );
            })}
          </select>
        </label>
        <label>
          Serie anteprima
          <select
            value={seriesKey}
            onChange={(event) => setSeriesKey(event.target.value)}
          >
            <option value="">Nessuna serie</option>
            {series.map((item, index) => {
              const key = latestItemSelectionKey(item, index);
              return (
                <option key={key} value={key}>
                  {latestPreviewItemLabel(item)}
                </option>
              );
            })}
          </select>
        </label>
      </div>
      <Button
        type="button"
        variant="secondary"
        size="compact"
        onClick={refreshPreview}
        disabled={!template.trim() || loading}
      >
        <RefreshCw
          size={15}
          className={loading ? "animate-spin" : ""}
          aria-hidden="true"
        />
        Aggiorna anteprima
      </Button>
      <WorkspaceChoiceGroup
        className="latest-preview-tabs"
        ariaLabel="Tipo anteprima"
        idPrefix="latest-preview-tab"
        mode="tab"
        value={activeKind}
        options={previewKinds.map((kind) => ({
          id: kind,
          content: kind === "movie" ? "Film" : "Serie TV",
          controls: `latest-preview-panel-${kind}`,
        }))}
        onChange={(kind) => setActiveKind(kind as PreviewKind)}
      />
      <div
        id={`latest-preview-panel-${activeKind}`}
        className="latest-preview-scroll"
        role="tabpanel"
        aria-labelledby={`latest-preview-tab-${activeKind}`}
        tabIndex={0}
      >
        {activeKind === "movie" ? (
          <PreviewItem
            label="Film"
            item={movie}
            preview={result?.previews.movie}
          />
        ) : (
          <PreviewItem
            label="Serie TV"
            item={show}
            preview={result?.previews.series}
          />
        )}
      </div>
    </section>
  );
}

function PreviewItem({
  label,
  item,
  preview,
}: {
  label: string;
  item?: LatestItem;
  preview?: LatestPreview["previews"]["movie"];
}) {
  const message = preview?.error
    ? preview.error
    : preview?.message ||
      "Salva o modifica un preset, poi aggiorna l'anteprima.";
  return (
    <article className="latest-preview-item">
      <header>
        <strong>{label}</strong>
        <span>{item?.title || "Nessun contenuto"}</span>
      </header>
      {preview?.image_enabled && preview.image_url ? (
        <div className="latest-preview-image">
          <img src={preview.image_url} alt="" />
        </div>
      ) : (
        <div className="latest-preview-image latest-preview-image--empty">
          <Image size={20} aria-hidden="true" />
        </div>
      )}
      <div
        className="latest-preview-message"
        dangerouslySetInnerHTML={{ __html: sanitizeTelegramHtml(message) }}
      />
    </article>
  );
}

export { LatestNotificationPreview };
