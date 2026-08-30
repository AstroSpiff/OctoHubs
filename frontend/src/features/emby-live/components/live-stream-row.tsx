import { LiveStreamStatus } from "@/features/emby-live/components/live-stream-status";
import {
  streamDisplayTitle,
  streamFlowSummary,
  streamPlaybackSummary,
  streamProgress,
} from "@/features/emby-live/presentation";
import type { EmbyLiveStream } from "@/features/emby-live/types";

type StreamWithServer = EmbyLiveStream & {
  serverName: string;
  serverId: string;
};

type StreamDetailGroup = {
  title: string;
  items: Array<[string, string]>;
};

function presentItems(items: Array<[string, string | undefined | null | false]>) {
  return items.filter((entry): entry is [string, string] => Boolean(entry[1]));
}

function LiveStreamRow({ stream }: { stream: StreamWithServer }) {
  const progress = streamProgress(stream);
  const playback = streamPlaybackSummary(stream);
  const flow = streamFlowSummary(stream);
  const transcodeReasons = Array.isArray(stream.transcode_reasons)
    ? stream.transcode_reasons
    : [];
  const detailGroups: StreamDetailGroup[] = [
    {
      title: "Generale",
      items: presentItems([
        ["Server", stream.serverName],
        ["Utente", stream.user],
        ["Stato", stream.state],
      ]),
    },
    {
      title: "Client e rete",
      items: presentItems([
        ["Dispositivo", stream.device],
        ["Client", [stream.client, stream.app_version].filter(Boolean).join(" ")],
        ["Rete", [stream.ip, stream.protocol].filter(Boolean).join(" · ")],
      ]),
    },
    {
      title: "Tracce",
      items: presentItems([
        ["Video", stream.video_label],
        ["Audio", stream.audio_label],
      ]),
    },
    {
      title: "Transcodifica",
      items: presentItems([
        ["Flusso", flow !== "N/D" ? flow : ""],
        ["Motivi", transcodeReasons.join(", ")],
      ]),
    },
    {
      title: "Transcode Guard",
      items: presentItems([
        ["Regola", stream.transcode_guard?.rule_name || ""],
        ["Motivo", stream.transcode_guard?.reason || ""],
      ]),
    },
  ].filter((group) => group.items.length);

  return (
    <article className="emby-live-stream">
      <div className="emby-live-stream-summary">
        <div className="emby-live-stream-copy">
          <h4>{streamDisplayTitle(stream)}</h4>
          <p>
            {[stream.user, stream.serverName, stream.client || stream.device, stream.state]
              .filter(Boolean)
              .join(" · ") || "Dettagli stream non disponibili"}
          </p>
        </div>
        <LiveStreamStatus stream={stream} />
      </div>
      {progress !== null ? (
        <div className="emby-live-stream-progress" aria-label={`Avanzamento riproduzione ${progress}%`}>
          <div><span>Riproduzione</span><small>{playback}</small></div>
          <i><b style={{ width: `${progress}%` }} /></i>
        </div>
      ) : <small className="emby-live-stream-progress-unavailable">Avanzamento non disponibile</small>}
      {detailGroups.length ? (
        <details className="emby-live-stream-details">
          <summary>Dettagli flusso</summary>
          <div className="emby-live-stream-detail-groups">
            {detailGroups.map((group) => (
              <section key={group.title} className="emby-live-stream-detail-group">
                <h5>{group.title}</h5>
                <dl>
                  {group.items.map(([label, value]) => (
                    <div key={label}><dt>{label}</dt><dd>{value}</dd></div>
                  ))}
                </dl>
              </section>
            ))}
          </div>
        </details>
      ) : null}
    </article>
  );
}

export { LiveStreamRow };
export type { StreamWithServer };
