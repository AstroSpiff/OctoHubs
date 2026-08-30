import {
  streamModePresentation,
  transcodeGuardPresentation,
  type StreamStatusPresentation,
} from "@/features/emby-live/stream-status-presentation";
import type { EmbyLiveStream } from "@/features/emby-live/types";

function LiveStreamStatus({ stream }: { stream: EmbyLiveStream }) {
  return (
    <div className="emby-live-stream-status" aria-label="Stato del flusso e del Transcode Guard">
      <StreamStatusItem label="Video" status={streamModePresentation(stream.video_mode)} />
      <StreamStatusItem label="Audio" status={streamModePresentation(stream.audio_mode)} />
      <StreamStatusItem label="Transcode Guard" status={transcodeGuardPresentation(stream.transcode_guard)} />
    </div>
  );
}

function StreamStatusItem({
  label,
  status,
}: {
  label: string;
  status: StreamStatusPresentation;
}) {
  return (
    <div className={`emby-live-stream-status-item is-${status.tone}`}>
      <span>{label}</span>
      <strong>{status.label}</strong>
    </div>
  );
}

export { LiveStreamStatus };
