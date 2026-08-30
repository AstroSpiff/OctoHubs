import { describe, expect, it } from "vitest";

import { shouldScheduleRequestRulesAutosave } from "@/features/research/request-rules-autosave";

describe("request rules autosave", () => {
  it("schedules only unattempted dirty revisions", () => {
    expect(
      shouldScheduleRequestRulesAutosave({
        dirty: true,
        saving: false,
        revision: 3,
        lastAttemptedRevision: 2,
      }),
    ).toBe(true);
    expect(
      shouldScheduleRequestRulesAutosave({
        dirty: true,
        saving: false,
        revision: 3,
        lastAttemptedRevision: 3,
      }),
    ).toBe(false);
  });

  it("waits while a save is already running", () => {
    expect(
      shouldScheduleRequestRulesAutosave({
        dirty: true,
        saving: true,
        revision: 4,
        lastAttemptedRevision: 3,
      }),
    ).toBe(false);
  });
});
