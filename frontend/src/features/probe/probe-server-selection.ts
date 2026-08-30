type ProbeServerChoice = { id: string };

function selectedAvailableProbeServerId(
  selectedServerId: string,
  servers: readonly ProbeServerChoice[],
): string {
  if (servers.some((server) => server.id === selectedServerId)) {
    return selectedServerId;
  }
  return servers[0]?.id || "";
}

export { selectedAvailableProbeServerId };
