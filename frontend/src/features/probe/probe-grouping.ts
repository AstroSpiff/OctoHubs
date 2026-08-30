import type {
  ProbeBlacklistItem,
  ProbeHistoryItem,
  ProbeQueueItem,
} from "@/features/probe/types";

type ProbeListItem = ProbeQueueItem | ProbeHistoryItem | ProbeBlacklistItem;

type ProbeLibraryGroup = {
  id: string;
  label: string;
  items: ProbeListItem[];
};

function groupProbeItemsByLibrary(
  items: ProbeListItem[],
  serverNames: Record<string, string>,
): ProbeLibraryGroup[] {
  const groups = new Map<string, ProbeLibraryGroup>();

  items.forEach((item) => {
    const libraryName = item.library_name || "Libreria sconosciuta";
    const serverName = item.server_id ? serverNames[item.server_id] : "";
    const libraryId = item.library_id || libraryName;
    const id = `${item.server_id || ""}:${libraryId}`;
    const group = groups.get(id) || {
      id,
      label: serverName ? `${serverName} - ${libraryName}` : libraryName,
      items: [],
    };
    group.items.push(item);
    groups.set(id, group);
  });

  return [...groups.values()].sort((left, right) =>
    left.label.localeCompare(right.label, "it"),
  );
}

export { groupProbeItemsByLibrary };
export type { ProbeLibraryGroup, ProbeListItem };
