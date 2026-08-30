import type { LibrarySettingItem } from "@/features/user-settings/types";

type LandingOption = { value: string; label: string };

function libraryLandingKey(item: LibrarySettingItem): string {
  return item.collection_type?.toLowerCase() === "livetv"
    ? "landing-livetv"
    : `landing-${item.id}`;
}

function libraryLandingOptions(collectionType?: string): LandingOption[] {
  const options: LandingOption[] = [{ value: "", label: "Predefinito" }];
  switch (collectionType?.toLowerCase()) {
    case "movies":
      return [...options, { value: "movies", label: "Film" }, { value: "suggestions", label: "Suggerimenti" }, { value: "favorites", label: "Preferiti" }, { value: "collections", label: "Collezioni" }, { value: "genres", label: "Generi" }];
    case "tvshows":
      return [...options, { value: "shows", label: "Serie" }, { value: "suggestions", label: "Suggerimenti" }, { value: "latest", label: "Ultimi episodi" }, { value: "favorites", label: "Preferiti" }, { value: "genres", label: "Generi" }];
    case "music":
      return [...options, { value: "music", label: "Musica" }, { value: "albumartists", label: "Artisti album" }, { value: "albums", label: "Album" }, { value: "artists", label: "Artisti" }, { value: "playlists", label: "Playlist" }, { value: "genres", label: "Generi" }];
    case "livetv":
      return [...options, { value: "suggestions", label: "Suggerimenti" }, { value: "guide", label: "Guida" }, { value: "channels", label: "Canali" }, { value: "recordings", label: "Registrazioni" }];
    default:
      return [...options, { value: "folder", label: "Cartella" }, { value: "latest", label: "Recenti" }, { value: "favorites", label: "Preferiti" }];
  }
}

export { libraryLandingKey, libraryLandingOptions };
