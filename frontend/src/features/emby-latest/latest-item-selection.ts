import type { LatestItem } from "@/features/emby-latest/types";

function latestItemSelectionKey(item: LatestItem, index: number) {
  const identity = [
    item.signature || item.item_id,
    item.batch_id,
    item.update_type || item.update_label,
    item.added_at || item.premiere_date,
  ]
    .filter(Boolean)
    .join("-");

  return `${item.server_id || "server"}-${identity || index}`;
}

function reconcileLatestItemSelection(
  items: LatestItem[],
  selectedKey: string,
) {
  if (
    selectedKey &&
    items.some(
      (item, index) => latestItemSelectionKey(item, index) === selectedKey,
    )
  )
    return selectedKey;
  return items.length ? latestItemSelectionKey(items[0], 0) : "";
}

function latestPreviewRequestKey(
  template: string,
  items: Partial<Record<"movie" | "series", LatestItem>>,
) {
  const itemKey = (item: LatestItem | undefined) =>
    item ? canonicalPreviewValue(item) : "";
  return [template, itemKey(items.movie), itemKey(items.series)].join("\u001e");
}

function canonicalPreviewValue(value: unknown): string {
  if (value === null || typeof value !== "object") {
    return JSON.stringify(value) ?? "null";
  }
  if (Array.isArray(value)) {
    return `[${value.map(canonicalPreviewValue).join(",")}]`;
  }
  const record = value as Record<string, unknown>;
  return `{${Object.keys(record)
    .filter((key) => record[key] !== undefined)
    .sort()
    .map(
      (key) =>
        `${JSON.stringify(key)}:${canonicalPreviewValue(record[key])}`,
    )
    .join(",")}}`;
}

export {
  latestItemSelectionKey,
  latestPreviewRequestKey,
  reconcileLatestItemSelection,
};
