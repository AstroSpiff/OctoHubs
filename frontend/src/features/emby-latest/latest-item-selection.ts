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

export { latestItemSelectionKey, reconcileLatestItemSelection };
