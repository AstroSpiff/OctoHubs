const routeTitles: Array<{ path: string; title: string }> = [
  { path: "/emby-live", title: "Emby Live" },
  { path: "/transcode-guard/rules", title: "Regole Transcode Guard" },
  { path: "/transcode-guard", title: "Transcode Guard" },
  { path: "/stream-stats", title: "Statistiche stream" },
  { path: "/users/icons", title: "Icone utenti" },
  { path: "/users", title: "Utenti" },
  { path: "/collections", title: "Collezioni" },
  { path: "/libraries", title: "Librerie" },
  { path: "/latest", title: "Pubblicazioni" },
  { path: "/probe", title: "Media Probe" },
  { path: "/research", title: "Ricerca" },
  { path: "/configuration", title: "Configurazione" },
];

function applicationTitle(pathname: string): string {
  const match = routeTitles.find(({ path }) => pathname === path);
  return match ? `${match.title} | OctoHubs` : "OctoHubs";
}

export { applicationTitle };
