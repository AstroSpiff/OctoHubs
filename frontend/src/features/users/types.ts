export type UserAccessStatus = "all" | "active" | "remote_disabled" | "account_disabled";
export type UserGroupType = "all" | "single" | "linked";
export type UserSort =
  | "name_asc_server_asc"
  | "name_asc_server_desc"
  | "name_desc_server_asc"
  | "name_desc_server_desc"
  | "server_asc_name_asc"
  | "server_asc_name_desc"
  | "server_desc_name_asc"
  | "server_desc_name_desc"
  | "members";

export type EmbyUser = {
  server_id: string;
  server_name: string;
  server_alias?: string;
  server_icon?: string;
  server_icon_color?: string;
  server_icon_style?: string;
  user_id: string;
  name: string;
  image_url?: string;
  is_disabled: boolean;
  is_user_disabled: boolean;
  is_remote_disabled: boolean;
  enable_remote_access: boolean;
  enable_downloading?: boolean;
  has_password?: boolean;
  is_admin: boolean;
  is_leader: boolean;
  last_login?: string | null;
  password_status?: string;
  password_saved?: boolean;
  password_mismatch?: boolean;
  password_mismatch_count?: number;
  settings_status?: string;
  settings_saved?: boolean;
  settings_mismatch?: boolean;
  settings_mismatch_count?: number;
};

export type EmbyUserDetails = {
  last_activity_date?: string | null;
  date_created?: string | null;
  last_played_date?: string | null;
  last_played_title?: string | null;
  has_password?: boolean;
  connect_user_name?: string | null;
  connect_link_type?: string | null;
};

export type EmbyUserGroup = {
  id: string;
  name: string;
  users: EmbyUser[];
  is_linked: boolean;
  is_owners?: boolean;
  auto_sync?: boolean;
  sync_type?: "merge" | "one_way";
  sync_resume?: boolean;
  sync_playstate?: boolean;
  sync_config?: boolean;
  sync_library_access?: boolean;
  sync_favorites?: boolean;
  sync_playlists?: boolean;
  config_categories?: string[];
  playstate_bootstrap_done?: boolean;
  favorites_bootstrap_done?: boolean;
  playlists_bootstrap_done?: boolean;
  last_sync_at?: string | null;
  last_sync_status?: string | null;
  last_sync_message?: string | null;
  password_status?: string;
  password_saved?: boolean;
  password_mismatch?: boolean;
  password_mismatch_count?: number;
  settings_status?: string;
  settings_saved?: boolean;
  settings_mismatch?: boolean;
  settings_mismatch_count?: number;
};

export type GroupSyncSettings = Pick<
  EmbyUserGroup,
  | "auto_sync"
  | "sync_type"
  | "sync_resume"
  | "sync_playstate"
  | "sync_config"
  | "sync_library_access"
  | "sync_favorites"
  | "sync_playlists"
  | "config_categories"
  | "playstate_bootstrap_done"
  | "favorites_bootstrap_done"
  | "playlists_bootstrap_done"
>;

export type SaveGroupSyncSettingsInput = GroupSyncSettings & { group_id: string };

export type EmbyUserServer = {
  id: string;
  name: string;
  icon?: string;
  icon_color?: string;
  icon_style?: string;
};

export type UsersDashboard = {
  groups: EmbyUserGroup[];
  servers: EmbyUserServer[];
};

export type UsersFilters = {
  search: string;
  groupType: UserGroupType;
  serverIds: string[];
  statuses: UserAccessStatus[];
  iconProfileIds: string[];
  sort: UserSort;
};

export type UserActionFailure = {
  server_id?: string;
  user_id?: string | null;
  username?: string;
  stage?: string;
  error?: unknown;
};

export type UserActionResult = {
  ok: boolean;
  status?: "success" | "partial" | "error" | string;
  error?: string;
  message?: string;
  failed?: UserActionFailure[] | string[];
  created?: unknown[];
  reconciliation_required?: boolean;
  result?: {
    ok?: boolean;
    status?: string;
    created?: unknown[];
    failed?: UserActionFailure[] | string[];
    reconciliation_required?: boolean;
  };
};

export type LinkUserSelection = {
  user: EmbyUser;
  groupId: string;
  groupName: string;
  groupIsLinked: boolean;
};

export type LinkUsersInput = {
  selections: LinkUserSelection[];
  targetGroupId?: string;
  leaderKey?: string;
};

export type PasswordTarget =
  | { scope: "group"; groupId: string; name: string; mismatchCount?: number }
  | { scope: "user"; serverId: string; userId: string; name: string; hasEmbyPassword?: boolean; mismatch?: boolean };

export type CloneUserInput = {
  source: EmbyUser;
  targetServerId: string;
  newUsername: string;
  syncConfig: boolean;
  syncPlaystate: boolean;
  syncResume: boolean;
  syncLibraryAccess: boolean;
  syncFavorites: boolean;
  syncPlaylists: boolean;
  linkGroup: boolean;
  configCategories: string[];
};

export type BulkCloneSource = {
  user: EmbyUser;
  newUsername: string;
  linkGroup: boolean;
};

export type BulkCloneInput = {
  sources: BulkCloneSource[];
  targetServerIds: string[];
  syncConfig: boolean;
  syncPlaystate: boolean;
  syncResume: boolean;
  syncLibraryAccess: boolean;
  syncFavorites: boolean;
  syncPlaylists: boolean;
  configCategories: string[];
  retryJobs?: Array<{ source: BulkCloneSource; targetServerId: string }>;
};

export type BulkCloneResult = {
  completed: number;
  failed: Array<{ source: EmbyUser; targetServerId: string; message: string }>;
};
