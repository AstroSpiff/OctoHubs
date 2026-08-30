import { describe, expect, it } from "vitest";

import { createGuardRule, validationMessage } from "@/features/transcode-guard-settings/rule-model";

describe("Transcode Guard rule model", () => {
  it("creates a disabled rule so a new policy cannot be enabled accidentally", () => {
    expect(createGuardRule().enabled).toBe(false);
  });

  it("requires a server only for an enabled rule", () => {
    const rule = createGuardRule();
    expect(validationMessage({ enabled: true, poll_interval_seconds: 5, stream_history_retention_days: 0, rules: [rule] })).toBe("");
    expect(validationMessage({ enabled: true, poll_interval_seconds: 5, stream_history_retention_days: 0, rules: [{ ...rule, enabled: true }] })).toContain("Seleziona almeno un server");
  });
});
