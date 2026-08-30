import {
  libraryIdentityIds,
  libraryItemIsSelected,
  unresolvedLibraryIds,
} from "@/features/user-settings/library-multi-selection";
import type {
  LibrarySettingItem,
  UserSettings,
} from "@/features/user-settings/types";

type LibraryAccess = UserSettings["libraries"];

function selectedLibraryAccessIds(libraries: LibraryAccess): Set<string> {
  return new Set((libraries.items || []).map(String));
}

function selectedLibraryGroups(
  itemIds: ReadonlySet<string>,
  items: LibrarySettingItem[],
): Record<string, true> {
  return Object.fromEntries(
    items
      .filter((item) => item.group_key && libraryItemIsSelected(item, itemIds))
      .map((item) => [String(item.group_key), true]),
  );
}

function customLibraryAccess(
  items: LibrarySettingItem[],
  selectedIds: Iterable<string>,
): LibraryAccess {
  const itemIds = new Set([...selectedIds].map(String));
  return {
    mode: "custom",
    items: [...itemIds],
    groups: selectedLibraryGroups(itemIds, items),
  };
}

function setLibraryAccessMode(
  libraries: LibraryAccess,
  items: LibrarySettingItem[],
  mode: "all" | "custom",
): LibraryAccess {
  if (mode === "all") return { mode: "all", items: [], groups: {} };
  if (libraries.mode === "all") {
    return customLibraryAccess(items, items.map((item) => item.id));
  }
  return customLibraryAccess(items, libraries.items || []);
}

function toggleLibraryAccessItem(
  libraries: LibraryAccess,
  items: LibrarySettingItem[],
  item: LibrarySettingItem,
  checked: boolean,
): LibraryAccess {
  const selectedIds = selectedLibraryAccessIds(libraries);
  if (checked) {
    if (!libraryItemIsSelected(item, selectedIds)) selectedIds.add(String(item.id));
  } else {
    for (const id of libraryIdentityIds(item)) selectedIds.delete(id);
  }
  return customLibraryAccess(items, selectedIds);
}

function unresolvedLibraryAccessIds(
  libraries: LibraryAccess,
  items: LibrarySettingItem[],
): string[] {
  return libraries.mode === "custom"
    ? unresolvedLibraryIds(libraries.items || [], items)
    : [];
}

function removeUnresolvedLibraryAccessId(
  libraries: LibraryAccess,
  items: LibrarySettingItem[],
  id: string,
): LibraryAccess {
  return customLibraryAccess(
    items,
    (libraries.items || []).map(String).filter((item) => item !== id),
  );
}

export {
  libraryItemIsSelected,
  removeUnresolvedLibraryAccessId,
  selectedLibraryAccessIds,
  setLibraryAccessMode,
  toggleLibraryAccessItem,
  unresolvedLibraryAccessIds,
};
