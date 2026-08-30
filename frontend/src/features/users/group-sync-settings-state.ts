import {
  defaultUserConfigurationCategoryIds,
} from "@/features/users/user-configuration-categories";
import type { EmbyUserGroup, GroupSyncSettings } from "@/features/users/types";

const comparableKeys = [
  "auto_sync",
  "sync_type",
  "sync_resume",
  "sync_playstate",
  "sync_config",
  "sync_library_access",
  "sync_favorites",
  "sync_playlists",
] as const satisfies ReadonlyArray<keyof GroupSyncSettings>;

function groupSyncSettingsFrom(group: EmbyUserGroup): GroupSyncSettings {
  return {
    auto_sync: group.auto_sync === true,
    sync_type: group.sync_type === "one_way" ? "one_way" : "merge",
    sync_resume: group.sync_resume === true,
    sync_playstate: group.sync_playstate !== false,
    sync_config: group.sync_config === true,
    sync_library_access: group.sync_library_access === true,
    sync_favorites: group.sync_favorites === true,
    sync_playlists: group.sync_playlists === true,
    config_categories: group.config_categories?.length
      ? group.config_categories
      : [...defaultUserConfigurationCategoryIds],
    playstate_bootstrap_done: group.playstate_bootstrap_done === true,
    favorites_bootstrap_done: group.favorites_bootstrap_done === true,
    playlists_bootstrap_done: group.playlists_bootstrap_done === true,
  };
}

function groupSyncSettingsMatch(
  first: GroupSyncSettings,
  second: GroupSyncSettings,
): boolean {
  const firstCategories = first.config_categories || [];
  const secondCategories = second.config_categories || [];
  return (
    firstCategories.length === secondCategories.length &&
    firstCategories.every((category) => secondCategories.includes(category)) &&
    comparableKeys.every((key) => first[key] === second[key])
  );
}

export { groupSyncSettingsFrom, groupSyncSettingsMatch };
