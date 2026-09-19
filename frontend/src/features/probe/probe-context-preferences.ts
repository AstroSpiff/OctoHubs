import {
  browserLocalStorage,
  readStoredValue,
  writeStoredValue,
} from "@/lib/safe-web-storage";

const probeLibraryServerStorageKey = "octohubs.probe.library-server";
const probeRecentServerStorageKey = "octohubs.probe.recent-server";

function readProbeLibraryServerId(): string {
  return readStoredValue(browserLocalStorage(), probeLibraryServerStorageKey) || "";
}

function readProbeRecentServerId(): string {
  return readStoredValue(browserLocalStorage(), probeRecentServerStorageKey) || "all";
}

function persistProbeLibraryServerId(serverId: string): void {
  writeStoredValue(
    browserLocalStorage(),
    probeLibraryServerStorageKey,
    serverId,
  );
}

function persistProbeRecentServerId(serverId: string): void {
  writeStoredValue(
    browserLocalStorage(),
    probeRecentServerStorageKey,
    serverId,
  );
}

export {
  persistProbeLibraryServerId,
  persistProbeRecentServerId,
  probeLibraryServerStorageKey,
  probeRecentServerStorageKey,
  readProbeLibraryServerId,
  readProbeRecentServerId,
};
