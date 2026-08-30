import { describe, expect, it } from "vitest";

import {
  scanSummaryItemKey,
  scanTargetForItem,
  scanTargetsFromItems,
} from "@/features/research/scan-summary-selection";

describe("scan summary selection", () => {
  const firstSeason = { request_id: 11, season: 1 };
  const secondSeason = { request_id: 11, season: 2 };

  it("keeps row keys separate while merging seasons for the API", () => {
    expect(scanSummaryItemKey(firstSeason)).toBe("11:1");
    expect(scanSummaryItemKey(secondSeason)).toBe("11:2");
    expect(scanTargetsFromItems([secondSeason, firstSeason])).toEqual([
      { request_id: 11, seasons: [1, 2], force: false },
    ]);
  });

  it("lets an all-seasons target take precedence", () => {
    expect(
      scanTargetsFromItems([
        firstSeason,
        { request_id: 11, season: null },
        secondSeason,
      ]),
    ).toEqual([{ request_id: 11, seasons: null, force: false }]);
  });

  it("builds a direct target for quick searches", () => {
    expect(scanTargetForItem(firstSeason)).toEqual({
      request_id: 11,
      seasons: [1],
      force: false,
    });
  });
});
