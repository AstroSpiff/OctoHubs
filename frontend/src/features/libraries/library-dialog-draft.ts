import type {
  LibraryActionTarget,
  LibraryGroup,
} from "@/features/libraries/types";

type LibraryAssociationDraft = Record<string, string>;

function normalizedAssociationValue(value: string | undefined) {
  return value?.trim() || "";
}

function libraryAssociationDraftMatches(
  draft: LibraryAssociationDraft,
  baseline: LibraryAssociationDraft,
) {
  const keys = new Set([...Object.keys(draft), ...Object.keys(baseline)]);
  return [...keys].every(
    (key) =>
      normalizedAssociationValue(draft[key]) ===
      normalizedAssociationValue(baseline[key]),
  );
}

function libraryGroupOrderMatches(
  draft: LibraryGroup[],
  baseline: LibraryGroup[],
) {
  return (
    draft.length === baseline.length &&
    draft.every((group, index) => {
      const saved = baseline[index];
      return (
        saved?.collection_type === group.collection_type &&
        saved.group_name === group.group_name
      );
    })
  );
}

function libraryServerOrderMatches(
  draft: LibraryActionTarget[],
  baseline: LibraryActionTarget[],
) {
  return (
    draft.length === baseline.length &&
    draft.every((server, index) => baseline[index]?.id === server.id)
  );
}

export {
  libraryAssociationDraftMatches,
  libraryGroupOrderMatches,
  libraryServerOrderMatches,
};
