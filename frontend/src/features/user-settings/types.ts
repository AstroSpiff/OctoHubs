export type SettingsScope = "policy" | "config" | "display_preferences";

export type SettingsTarget =
  | { scope: "group"; groupId: string; name: string; mismatchCount?: number }
  | { scope: "user"; serverId: string; userId: string; name: string; mismatch?: boolean };

export type SettingsOption = {
  value: string | number | boolean;
  label: string;
  feature_type?: string;
};

export type SettingsField = {
  key: string;
  label?: string;
  description?: string;
  type?: string;
  group?: string;
  options?: SettingsOption[];
  min?: number;
  max?: number;
  max_length?: number;
  placeholder?: string;
  hidden?: boolean;
};

export type SettingsCategory = {
  id: string;
  label?: string;
  description?: string;
  libraries?: boolean;
  policy?: SettingsField[];
  config?: SettingsField[];
  display_preferences?: SettingsField[];
};

export type UserSettings = {
  policy: Record<string, unknown>;
  config: Record<string, unknown>;
  display_preferences: Record<string, unknown>;
  libraries: { mode?: "all" | "custom"; items?: string[]; groups?: Record<string, unknown> };
};

export type SettingsSchema = {
  schema_version: number;
  categories: SettingsCategory[];
};

export type LibrarySettingItem = {
  id: string;
  name?: string;
  collection_type?: string;
  alt_ids?: string[];
  group_key?: string;
};

export type SettingsFeatureItem = {
  id: string;
  name?: string;
  feature_type?: string;
};

export type SettingsInfo = {
  ok: boolean;
  saved: boolean;
  settings: Partial<UserSettings>;
  updated_at?: string | null;
  from_emby?: boolean;
  library_items?: LibrarySettingItem[];
  feature_items?: SettingsFeatureItem[];
};

export type SettingsPreset = {
  id: string;
  label: string;
  description?: string;
  settings: Partial<UserSettings>;
  apply_libraries?: boolean;
};
