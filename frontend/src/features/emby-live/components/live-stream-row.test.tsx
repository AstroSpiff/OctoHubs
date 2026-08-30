import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { LiveStreamRow } from "@/features/emby-live/components/live-stream-row";

describe("LiveStreamRow", () => {
  it("keeps the complete stream diagnostics that were previously only in Operations", () => {
    const markup = renderToStaticMarkup(
      <LiveStreamRow
        stream={{
          session_id: "session-1",
          title: "Film di prova",
          user: "Roy",
          device: "Apple TV",
          client: "Emby for tvOS",
          app_version: "4.8.0",
          ip: "192.168.1.20",
          protocol: "https",
          state: "Playing",
          paused: false,
          video_mode: "transcodifica",
          audio_mode: "diretto",
          video_label: "H.264 1080p",
          audio_label: "AAC stereo",
          stream_container: "mkv",
          transcode_container: "ts",
          transcode_bitrate: 4_000_000,
          position: "00:12:00",
          duration: "01:40:00",
          playback_percent: 12,
          transcode_reasons: ["Bitrate"],
          transcode_guard: { enabled: true, should_enforce: true },
          serverId: "green",
          serverName: "Green",
        }}
      />,
    );

    expect(markup).toContain("Film di prova");
    expect(markup).toContain("Video");
    expect(markup).toContain("Audio");
    expect(markup).toContain("Transcode Guard");
    expect(markup).toContain("Violazione rilevata");
    expect(markup).toContain("Dettagli flusso");
    expect(markup).toContain("Client e rete");
    expect(markup).toContain("Tracce");
    expect(markup).toContain("Transcodifica");
    expect(markup).toContain("192.168.1.20");
    expect(markup).toContain("H.264 1080p");
    expect(markup).toContain("AAC stereo");
    expect(markup).toContain("Bitrate");
    expect(markup.indexOf("Transcode Guard")).toBeLessThan(
      markup.indexOf("Riproduzione"),
    );
    expect(markup.indexOf("Riproduzione")).toBeLessThan(
      markup.indexOf("Dettagli flusso"),
    );
    expect(markup.indexOf("Client e rete")).toBeLessThan(
      markup.indexOf("Tracce"),
    );
  });
});
