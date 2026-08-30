import { describe, expect, it } from "vitest";

import {
  formatLiveTime,
  serverPresentation,
  streamDisplayTitle,
  streamFlowSummary,
  streamPlaybackSummary,
  streamProgress,
  taskProgress,
} from "@/features/emby-live/presentation";

describe("Emby Live presentation", () => {
  it("keeps a disabled configured server neutral", () => {
    expect(
      serverPresentation({
        server: { id: "green", name: "Green", enabled: false },
        status: { ok: false },
        running_tasks: [],
        streams: [],
        tasks_error: null,
        streams_error: null,
      }),
    ).toEqual({ label: "Disabilitato", severity: "neutral" });
  });

  it("formats an episode title and stream flow without hiding its target container", () => {
    const stream = {
      title: "Episodio",
      series_name: "Severance",
      year: 2022,
      season_number: 2,
      episode_number: 3,
      episode_title: "Memoria",
      stream_container: "mkv",
      transcode_container: "ts",
      transcode_bitrate: 8_000_000,
    } as never;
    expect(streamDisplayTitle(stream)).toBe(
      "Severance · (2022) · S02E03 · Memoria",
    );
    expect(streamFlowSummary(stream)).toBe("mkv -> ts (8000 kbps)");
  });

  it("keeps playback labels and progress inside a meaningful range", () => {
    const stream = {
      position: "00:35",
      duration: "01:20",
      playback_percent: 101.6,
    } as never;

    expect(streamProgress(stream)).toBe(100);
    expect(streamPlaybackSummary(stream)).toBe("00:35 / 01:20 · 100%");
    expect(
      streamProgress({ playback_percent: Number.NaN } as never),
    ).toBeNull();
    expect(taskProgress(Number.POSITIVE_INFINITY)).toBe(0);
    expect(taskProgress(101.6)).toBe(100);
  });

  it("keeps live timestamps compact while preserving seconds", () => {
    expect(formatLiveTime("2026-08-12T10:20:35+00:00")).toMatch(
      /\d{2}:\d{2}:\d{2}/,
    );
  });
});
