import type { LibrarySettingItem } from "@/features/user-settings/types";

function libraryIdentityIds(item: LibrarySettingItem): string[] {
  return [...new Set([item.id, ...(item.alt_ids || [])].map(String).filter(Boolean))];
}

function libraryItemIsSelected(
  item: LibrarySettingItem,
  selectedIds: ReadonlySet<string>,
): boolean {
  return libraryIdentityIds(item).some((id) => selectedIds.has(id));
}

function toggleLibraryItem(
  value: unknown,
  item: LibrarySettingItem,
  checked: boolean,
): string[] {
  const next = new Set(Array.isArray(value) ? value.map(String) : []);
  if (checked) {
    next.add(String(item.id));
  } else {
    for (const id of libraryIdentityIds(item)) next.delete(id);
  }
  return [...next];
}

function unresolvedLibraryIds(
  value: unknown,
  items: LibrarySettingItem[],
): string[] {
  const knownIds = new Set(items.flatMap(libraryIdentityIds));
  return [...new Set(Array.isArray(value) ? value.map(String) : [])]
    .filter((id) => id && !knownIds.has(id));
}

export {
  libraryIdentityIds,
  libraryItemIsSelected,
  toggleLibraryItem,
  unresolvedLibraryIds,
};
