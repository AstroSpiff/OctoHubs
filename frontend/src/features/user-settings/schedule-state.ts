import { boundedWholeNumberInput } from "@/lib/numeric-input";

type ScheduleEntry = {
  DayOfWeek: string;
  StartHour: number;
  EndHour: number;
};

function normalizeScheduleEntries(
  value: unknown,
  defaultDay: string,
): ScheduleEntry[] {
  if (!Array.isArray(value)) return [];
  return value
    .filter((entry): entry is Record<string, unknown> => Boolean(entry) && typeof entry === "object")
    .map((entry) => ({
      DayOfWeek: typeof entry.DayOfWeek === "string" && entry.DayOfWeek ? entry.DayOfWeek : defaultDay,
      StartHour: boundedWholeNumberInput(String(entry.StartHour ?? 0), 0, 23),
      EndHour: boundedWholeNumberInput(String(entry.EndHour ?? 23), 0, 23),
    }))
    .filter((entry) => Boolean(entry.DayOfWeek));
}

export { normalizeScheduleEntries };
export type { ScheduleEntry };
