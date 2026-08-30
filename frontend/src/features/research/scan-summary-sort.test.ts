import { describe, expect, it } from "vitest";

import {
  changeScanSummarySort,
  defaultScanSummarySort,
  sortScanSummaryItems,
} from "@/features/research/scan-summary-sort";

describe("scan summary sort", () => {
  const items = [
    { request_id: "12", title: "Zeta", results_found: 2 },
    { request_id: "3", title: "Alfa", results_found: 8 },
    { request_id: "9", title: "Beta", results_found: 1 },
  ];

  it("keeps backend order until the user explicitly chooses a sort", () => {
    expect(sortScanSummaryItems(items, defaultScanSummarySort)).toBe(items);
  });

  it("sorts legacy ID, title and results fields with a reversible direction", () => {
    expect(
      sortScanSummaryItems(items, { key: "id", direction: "asc" }).map(
        (item) => item.request_id,
      ),
    ).toEqual(["3", "9", "12"]);
    expect(
      sortScanSummaryItems(items, { key: "title", direction: "asc" }).map(
        (item) => item.title,
      ),
    ).toEqual(["Alfa", "Beta", "Zeta"]);
    expect(
      sortScanSummaryItems(items, { key: "results", direction: "desc" }).map(
        (item) => item.results_found,
      ),
    ).toEqual([8, 2, 1]);
    expect(changeScanSummarySort({ key: "title", direction: "asc" }, "title")).toEqual({
      key: "title",
      direction: "desc",
    });
  });
});
