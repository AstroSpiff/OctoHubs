import type {
  BulkCloneInput,
  EmbyUser,
  EmbyUserServer,
} from "@/features/users/types";
import { defaultUserConfigurationCategoryIds } from "@/features/users/user-configuration-categories";

function cloneUserDraft(
  users: EmbyUser[],
  servers: EmbyUserServer[],
): BulkCloneInput {
  return {
    sources: users.map((user) => ({
      user,
      newUsername: user.name,
      linkGroup: false,
    })),
    targetServerIds: servers
      .filter((server) => !users.every((user) => user.server_id === server.id))
      .map((server) => server.id),
    syncConfig: true,
    syncPlaystate: true,
    syncResume: false,
    syncLibraryAccess: true,
    syncFavorites: true,
    syncPlaylists: true,
    configCategories: [...defaultUserConfigurationCategoryIds],
  };
}

function cloneUserDraftMatches(first: BulkCloneInput, second: BulkCloneInput) {
  return (
    first.syncConfig === second.syncConfig &&
    first.syncPlaystate === second.syncPlaystate &&
    first.syncResume === second.syncResume &&
    first.syncLibraryAccess === second.syncLibraryAccess &&
    first.syncFavorites === second.syncFavorites &&
    first.syncPlaylists === second.syncPlaylists &&
    sameIds(first.targetServerIds, second.targetServerIds) &&
    sameIds(first.configCategories, second.configCategories) &&
    sameSources(first, second)
  );
}

function sameSources(first: BulkCloneInput, second: BulkCloneInput) {
  return (
    first.sources.length === second.sources.length &&
    first.sources.every((source, index) => {
      const other = second.sources[index];
      return (
        source.user.server_id === other?.user.server_id &&
        source.user.user_id === other?.user.user_id &&
        source.newUsername === other.newUsername &&
        source.linkGroup === other.linkGroup
      );
    })
  );
}

function sameIds(first: string[], second: string[]) {
  return first.length === second.length && first.every((id) => second.includes(id));
}

export { cloneUserDraft, cloneUserDraftMatches };
