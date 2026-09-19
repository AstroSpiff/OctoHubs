import type { ConfigurationServices, ServiceSettingsInput } from "@/features/configuration/types";

function serviceInputFromSnapshot(services: ConfigurationServices): ServiceSettingsInput {
  return {
    connections: {
      jellyseerr: { url: services.connections.jellyseerr.url },
      prowlarr: { url: services.connections.prowlarr.url },
      jackett: { url: services.connections.jackett.url },
      qbittorrent: { url: services.connections.qbittorrent.url, username: services.connections.qbittorrent.username },
      torrent_clients: (services.connections.torrent_clients || []).map((client) => ({
        id: client.id,
        name: client.name,
        kind: client.kind,
        url: client.url,
        username: client.username,
        enabled: client.enabled,
        is_default: client.is_default,
      })),
      tmdb: { language: services.connections.tmdb.language },
      mdblist: {},
      omdb: {},
    },
    trakt: { enabled: services.trakt.enabled, client_id: services.trakt.client_id },
    justwatch: { enabled: services.justwatch.enabled, locale: services.justwatch.locale },
  };
}

function splitKeys(value: string): string[] {
  return value.split(/[\n,]/).map((item) => item.trim()).filter(Boolean);
}

function serviceLabel(name: string): string {
  return ({
    jellyseerr: "Jellyseerr",
    prowlarr: "Prowlarr",
    jackett: "Jackett",
    qbittorrent: "Client Torrent",
    torrent_clients: "Client Torrent",
    mdblist: "MDBList",
    omdb: "OMDb",
    trakt: "Trakt",
    justwatch: "JustWatch",
    database: "Database",
  } as Record<string, string>)[name] || name;
}

export { serviceInputFromSnapshot, serviceLabel, splitKeys };
