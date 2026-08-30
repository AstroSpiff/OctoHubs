import type { ScanSummaryItem } from "@/features/research/types";

type ScanSummarySortKey = "default" | "id" | "title" | "results";
type ScanSummarySortDirection = "asc" | "desc";
type ScanSummarySort = {
  key: ScanSummarySortKey;
  direction: ScanSummarySortDirection;
};

const defaultScanSummarySort: ScanSummarySort = {
  key: "default",
  direction: "asc",
};

function changeScanSummarySort(
  current: ScanSummarySort,
  key: ScanSummarySortKey,
): ScanSummarySort {
  if (key === "default") return defaultScanSummarySort;
  if (current.key === key) {
    return {
      key,
      direction: current.direction === "asc" ? "desc" : "asc",
    };
  }
  return { key, direction: "asc" };
}

function sortScanSummaryItems(
  items: ScanSummaryItem[],
  sort: ScanSummarySort,
) {
  if (sort.key === "default") return items;
  const key = sort.key;
  const direction = sort.direction === "asc" ? 1 : -1;
  return [...items].sort((first, second) =>
    compareScanSummaryItems(first, second, key) * direction,
  );
}

function compareScanSummaryItems(
  first: ScanSummaryItem,
  second: ScanSummaryItem,
  key: Exclude<ScanSummarySortKey, "default">,
) {
  if (key === "id") {
    return compareNumericOrText(first.request_id, second.request_id);
  }
  if (key === "results") {
    return Number(first.results_found || 0) - Number(second.results_found || 0);
  }
  return String(first.title || "").localeCompare(String(second.title || ""), "it", {
    sensitivity: "base",
  });
}

function compareNumericOrText(first: string | number, second: string | number) {
  const firstNumber = Number(first);
  const secondNumber = Number(second);
  if (Number.isFinite(firstNumber) && Number.isFinite(secondNumber)) {
    return firstNumber - secondNumber;
  }
  return String(first).localeCompare(String(second), "it", { numeric: true });
}

export {
  changeScanSummarySort,
  defaultScanSummarySort,
  sortScanSummaryItems,
};
export type {
  ScanSummarySort,
  ScanSummarySortDirection,
  ScanSummarySortKey,
};
