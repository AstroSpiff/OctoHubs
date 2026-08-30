import { describe, expect, it } from "vitest";

import { normalizeScheduleEntries } from "@/features/user-settings/schedule-state";

describe("schedule state", () => {
  it("normalizes schedule hours using the legacy 0-23 range", () => {
    expect(normalizeScheduleEntries([
      { DayOfWeek: "Monday", StartHour: -2, EndHour: 26.8 },
      { DayOfWeek: "Tuesday", StartHour: "invalid" },
    ], "Sunday")).toEqual([
      { DayOfWeek: "Monday", StartHour: 0, EndHour: 23 },
      { DayOfWeek: "Tuesday", StartHour: 0, EndHour: 23 },
    ]);
  });
});
