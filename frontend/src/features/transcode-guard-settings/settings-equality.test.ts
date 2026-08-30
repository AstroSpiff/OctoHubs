import { describe, expect, it } from "vitest";

import { createGuardRule } from "@/features/transcode-guard-settings/rule-model";
import { transcodeGuardSettingsEqual } from "@/features/transcode-guard-settings/settings-equality";
import type { TranscodeGuardSettings } from "@/features/transcode-guard-settings/types";

function settings(): TranscodeGuardSettings {
  return {
    enabled: true,
    poll_interval_seconds: 10,
    stream_history_retention_days: 30,
    rules: [{ ...createGuardRule(), name: "Blocca transcodifica", server_ids: ["green"] }],
  };
}

describe("Transcode Guard settings equality", () => {
  it("accepts equal nested settings even when object keys arrive in a different order", () => {
    const left = settings();
    const right = {
      rules: [{ ...left.rules[0], server_ids: ["green"] }],
      stream_history_retention_days: 30,
      enabled: true,
      poll_interval_seconds: 10,
    };

    expect(transcodeGuardSettingsEqual(left, right)).toBe(true);
  });

  it("detects a changed nested rule or rule order", () => {
    const original = settings();
    const changedRule = { ...original, rules: [{ ...original.rules[0], max_warnings: 2 }] };
    const changedOrder = { ...original, rules: [...original.rules, createGuardRule()] };

    expect(transcodeGuardSettingsEqual(original, changedRule)).toBe(false);
    expect(transcodeGuardSettingsEqual(original, changedOrder)).toBe(false);
  });
});
