import type { SettingsScope } from "@/features/user-settings/types";

const settingsScopes = [
  "policy",
  "config",
  "display_preferences",
] as const satisfies readonly SettingsScope[];

function settingsScopeAtOffset(
  current: SettingsScope,
  offset: number,
): SettingsScope {
  const currentIndex = settingsScopes.indexOf(current);
  return settingsScopes[
    (currentIndex + offset + settingsScopes.length) % settingsScopes.length
  ];
}

export { settingsScopeAtOffset, settingsScopes };
