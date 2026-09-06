import { ExternalLink } from "@/components/ui/icons";
import { useEffect, useState } from "react";

import { RequestRuleFields } from "@/features/research/components/request-rule-fields";
import { RequestSeasonStatus } from "@/features/research/components/request-season-status";
import { useWorkspaceCapabilities } from "@/features/session/workspace-capabilities-context";
import { tmdbPosterUrl } from "@/features/research/presentation";
import {
  requestRuleCompactBreakpoint,
  requestRuleDetailsOpenForWidth,
} from "@/features/research/request-rule-details";
import type { RequestSearchRule, ResearchRequest } from "@/features/research/types";
import { safeExternalHttpUrl } from "@/lib/external-url";

function RequestRuleCard({ request, rule, disabled, onChange }: { request: ResearchRequest; rule: RequestSearchRule; disabled: boolean; onChange: (patch: Partial<RequestSearchRule>) => void }) {
  const { canMutate } = useWorkspaceCapabilities();
  const [rulesOpen, setRulesOpen] = useState(() => requestRuleDetailsOpenForWidth(
    typeof window === "undefined" ? undefined : window.innerWidth,
  ));
  const poster = tmdbPosterUrl(stringFrom(request.poster_url ?? request.poster_path));
  const mediaType = String(request.media_type || "").toLowerCase();
  const externalLinks = [["Jellyseerr", request.jellyseerr_url], ["Trakt", request.trakt_url], ["TMDB", request.tmdb_url]].map(([label, value]) => [label, safeExternalHttpUrl(value)]).filter((entry): entry is [string, string] => Boolean(entry[1]));
  const justWatchProviders = stringList(request.justwatch_providers);
  const justWatchTitle = justWatchProviders.length ? `Disponibile su JustWatch: ${justWatchProviders.join(", ")}` : "Disponibile su JustWatch";

  useEffect(() => {
    const compactViewport = window.matchMedia(`(max-width: ${requestRuleCompactBreakpoint}px)`);
    const syncVisibility = () => setRulesOpen(!compactViewport.matches);
    syncVisibility();
    compactViewport.addEventListener("change", syncVisibility);
    return () => compactViewport.removeEventListener("change", syncVisibility);
  }, []);

  return <article className={`research-request-row ${canMutate ? "" : "is-read-only"}`.trim()}>
    <div className="research-request-main">
      {canMutate ? <label className="research-request-enabled"><input type="checkbox" checked={rule.enabled} disabled={disabled} onChange={(event) => onChange({ enabled: event.target.checked })} aria-label={`Abilita ${request.title || "richiesta"}`} /></label> : null}
      <div className="research-request-poster">{poster ? <img src={poster} alt="" /> : <span>{mediaType === "tv" ? "TV" : "Film"}</span>}</div>
      <div className="research-request-copy">
        <div><strong>{String(request.title || "Titolo non disponibile")}</strong>{request.year ? <span>({String(request.year)})</span> : null}</div>
        <small>{[request.id ?? request.request_id, mediaType || "N/D", request.age].filter((value) => value !== undefined && value !== "").join(" · ")}</small>
        <RequestStatusBadges request={request} justWatchTitle={justWatchTitle} />
        {externalLinks.length ? <div className="research-request-links">{externalLinks.map(([label, href]) => <a key={label} href={href} target="_blank" rel="noreferrer">{label}<ExternalLink size={11} aria-hidden="true" /></a>)}</div> : null}
      </div>
    </div>
    {mediaType === "tv" && Array.isArray(request.season_status) ? <RequestSeasonStatus seasons={request.season_status} /> : null}
    {canMutate ? <details className="research-request-rules" open={rulesOpen} onToggle={(event) => setRulesOpen(event.currentTarget.open)}><summary>Regole ricerca</summary><RequestRuleFields rule={rule} mediaType={mediaType} disabled={disabled} onChange={onChange} /></details> : null}
  </article>;
}

function RequestStatusBadges({ request, justWatchTitle }: { request: ResearchRequest; justWatchTitle: string }) {
  return <div className="research-request-badges">
    {request.is_available ? <span className="is-available">Già disponibile</span> : null}
    {request.is_unreleased ? <span className="is-warning">Non pubblicato</span> : null}
    {request.will_skip ? <span className="is-muted">Ignorata dalle regole</span> : null}
    {request.release_date ? <span>Uscita: {String(request.release_date)}</span> : null}
    {request.justwatch_available ? <span className="is-justwatch" title={justWatchTitle}>JustWatch</span> : null}
  </div>;
}

function stringList(value: unknown): string[] {
  return Array.isArray(value) ? value.filter((entry): entry is string => typeof entry === "string" && Boolean(entry)) : [];
}

function stringFrom(value: unknown) {
  return typeof value === "string" ? value : "";
}

export { RequestRuleCard };
