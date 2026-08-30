export const userConfigurationCategories = [
  { id: "profile", label: "Profilo sicuro", defaultEnabled: true },
  { id: "access", label: "Accesso sicuro", defaultEnabled: true },
  { id: "display", label: "Schermo", defaultEnabled: true },
  { id: "home", label: "Home", defaultEnabled: true },
  { id: "playback_prefs", label: "Riproduzione", defaultEnabled: true },
  { id: "subtitles", label: "Sottotitoli", defaultEnabled: true },
  { id: "parental", label: "Parentale", defaultEnabled: false },
  { id: "profile_pin", label: "PIN profilo", defaultEnabled: true },
] as const;

export const defaultUserConfigurationCategoryIds = userConfigurationCategories
  .filter((category) => category.defaultEnabled)
  .map((category) => category.id);
