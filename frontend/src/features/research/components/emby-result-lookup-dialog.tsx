import { LoaderCircle, Server, X } from "@/components/ui/icons";
import { useQuery } from "@tanstack/react-query";

import { Button } from "@/components/ui/button";
import { DialogBackdrop } from "@/components/ui/dialog-backdrop";
import { lookupEmbyTitle } from "@/features/research/api";

type LookupTarget = { title: string; year?: string | number };

function EmbyResultLookupDialog({
  target,
  onClose,
}: {
  target: LookupTarget;
  onClose: () => void;
}) {
  const lookup = useQuery({
    queryKey: ["emby-result-lookup", target.title, target.year],
    queryFn: () => lookupEmbyTitle(target.title, target.year),
    staleTime: 60_000,
  });
  const details = lookup.data?.details;
  return (
    <DialogBackdrop className="research-dialog-backdrop" onDismiss={onClose}>
      <section
        className="research-dialog"
        role="dialog"
        aria-modal="true"
        aria-labelledby="emby-result-lookup-title"
      >
        <header>
          <div>
            <h2 id="emby-result-lookup-title" className="contextual-heading" title="Emby">Dettagli disponibilità</h2>
          </div>
          <Button
            type="button"
            variant="ghost"
            size="icon"
            title="Chiudi dettagli Emby"
            aria-label="Chiudi dettagli Emby"
            onClick={onClose}
          >
            <X size={17} aria-hidden="true" />
          </Button>
        </header>
        {lookup.isLoading ? (
          <div className="research-empty-state">
            <LoaderCircle
              size={18}
              className="animate-spin"
              aria-hidden="true"
            />{" "}
            Ricerca in Emby...
          </div>
        ) : null}
        {lookup.error ? (
          <p className="research-dialog-message is-error" role="alert">
            {lookup.error.message}
          </p>
        ) : null}
        {!lookup.isLoading && !lookup.error && !lookup.data?.found ? (
          <p className="research-dialog-message">
            {lookup.data?.message || "Titolo non trovato in Emby."}
          </p>
        ) : null}
        {details ? (
          <dl className="research-dialog-details">
            <dt>Titolo</dt>
            <dd>{details.title || target.title}</dd>
            <dt>Anno</dt>
            <dd>{details.year || "-"}</dd>
            <dt>Server</dt>
            <dd>
              <Server size={14} aria-hidden="true" /> {details.server || "-"}
            </dd>
            <dt>Video</dt>
            <dd>
              {[details.resolution, details.video_codec]
                .filter(Boolean)
                .join(" · ") || "-"}
            </dd>
            <dt>Audio</dt>
            <dd>{details.audio_codec || "-"}</dd>
            <dt>Bitrate</dt>
            <dd>
              {details.bitrate_mbps ? `${details.bitrate_mbps} Mbps` : "-"}
            </dd>
            <dt>Percorso</dt>
            <dd>{details.path || "-"}</dd>
            {details.audio_tracks?.length ? (
              <>
                <dt>Tracce audio</dt>
                <dd>{details.audio_tracks.join(" · ")}</dd>
              </>
            ) : null}
          </dl>
        ) : null}
      </section>
    </DialogBackdrop>
  );
}

export { EmbyResultLookupDialog };
export type { LookupTarget };
