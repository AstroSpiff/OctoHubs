export function librarySelectionAfterBucketToggle(
  selected: string[],
  bucketIds: string[],
  checked: boolean,
) {
  const bucketIdSet = new Set(bucketIds);

  return checked
    ? [...new Set([...selected, ...bucketIds])]
    : selected.filter((id) => !bucketIdSet.has(id));
}

function librarySelectionState(selected: string[], libraryIds: string[]) {
  const selectedIds = new Set(selected);
  const uniqueLibraryIds = [...new Set(libraryIds)];
  const selectedCount = uniqueLibraryIds.filter((id) => selectedIds.has(id)).length;
  const total = uniqueLibraryIds.length;

  return {
    selectedCount,
    total,
    checked: total > 0 && selectedCount === total,
    indeterminate: selectedCount > 0 && selectedCount < total,
  };
}

function selectedAvailableLibraryIds(selected: string[], libraryIds: string[]) {
  const availableIds = new Set(libraryIds);
  return [...new Set(selected)].filter((id) => availableIds.has(id));
}

export { librarySelectionState, selectedAvailableLibraryIds };
