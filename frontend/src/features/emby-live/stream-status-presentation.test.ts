import { describe, expect, it } from "vitest";

import {
  streamModePresentation,
  transcodeGuardPresentation,
} from "@/features/emby-live/stream-status-presentation";

describe("Emby Live stream status presentation", () => {
  it("keeps video and audio transport states separate", () => {
    expect(streamModePresentation("diretta")).toEqual({
      label: "Diretto",
      tone: "ok",
    });
    expect(streamModePresentation("transcodifica")).toEqual({
      label: "Transcodifica",
      tone: "warning",
    });
  });

  it("presents only real Transcode Guard states", () => {
    expect(transcodeGuardPresentation()).toEqual({
      label: "Non valutato",
      tone: "neutral",
    });
    expect(transcodeGuardPresentation({
      enabled: false,
      should_enforce: true,
    })).toEqual({
      label: "Violazione rilevata",
      tone: "warning",
    });
    expect(transcodeGuardPresentation({
      enabled: false,
      category: "direct",
      should_enforce: false,
    })).toEqual({
      label: "Conforme",
      tone: "ok",
    });
    expect(transcodeGuardPresentation({
      enabled: true,
      category: "direct",
      should_enforce: false,
    })).toEqual({
      label: "Conforme",
      tone: "ok",
    });
  });
});
