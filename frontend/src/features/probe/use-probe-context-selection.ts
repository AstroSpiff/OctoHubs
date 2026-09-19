import { useEffect, useMemo, useRef, useState } from "react";

import { selectedAvailableLibraryIds } from "@/features/probe/probe-library-selection";
import {
  persistProbeLibraryServerId,
  persistProbeRecentServerId,
  readProbeLibraryServerId,
  readProbeRecentServerId,
} from "@/features/probe/probe-context-preferences";
import { selectedAvailableProbeServerId } from "@/features/probe/probe-server-selection";
import type {
  ProbeLibrariesPayload,
  ProbeLibrary,
  ProbeScope,
  ProbeServer,
} from "@/features/probe/types";

function useProbeContextSelection({
  servers,
  libraries,
  confirmDiscardRecentConfigDraft,
  scope,
}: {
  servers: ProbeServer[];
  libraries?: ProbeLibrariesPayload;
  confirmDiscardRecentConfigDraft: () => Promise<boolean>;
  scope: ProbeScope;
}) {
  const [libraryServerId, setLibraryServerId] = useState(
    readProbeLibraryServerId,
  );
  const [recentServerId, setRecentServerId] = useState(
    readProbeRecentServerId,
  );
  const [discoveryLibraries, setDiscoveryLibraries] = useState<string[]>([]);
  const [processingLibraries, setProcessingLibraries] = useState<string[]>([]);
  const initializedLibrarySelection = useRef<string | null>(null);

  useEffect(() => {
    if (!servers.length) return;
    const availableLibraryServerId = selectedAvailableProbeServerId(
      libraryServerId,
      servers,
    );
    if (availableLibraryServerId !== libraryServerId) {
      setLibraryServerId(availableLibraryServerId);
      persistProbeLibraryServerId(availableLibraryServerId);
    }
    if (
      recentServerId !== "all" &&
      !servers.some((server) => server.id === recentServerId)
    ) {
      setRecentServerId("all");
      persistProbeRecentServerId("all");
    }
  }, [libraryServerId, recentServerId, servers]);

  const selectedLibraryData = useMemo<ProbeLibrary[]>(
    () => libraries?.servers[libraryServerId]?.libraries || [],
    [libraries, libraryServerId],
  );
  const availableLibraryIds = useMemo(
    () => selectedLibraryData.map((library) => library.id),
    [selectedLibraryData],
  );
  const selectedDiscoveryLibraryIds = useMemo(
    () => selectedAvailableLibraryIds(discoveryLibraries, availableLibraryIds),
    [availableLibraryIds, discoveryLibraries],
  );
  const selectedProcessingLibraryIds = useMemo(
    () => selectedAvailableLibraryIds(processingLibraries, availableLibraryIds),
    [availableLibraryIds, processingLibraries],
  );

  useEffect(() => {
    if (
      !libraryServerId ||
      !libraries ||
      initializedLibrarySelection.current === libraryServerId
    ) {
      return;
    }
    setDiscoveryLibraries((current) =>
      initializedLibrarySelection.current === libraryServerId
        ? selectedAvailableLibraryIds(current, availableLibraryIds)
        : availableLibraryIds,
    );
    setProcessingLibraries((current) =>
      initializedLibrarySelection.current === libraryServerId
        ? selectedAvailableLibraryIds(current, availableLibraryIds)
        : availableLibraryIds,
    );
    initializedLibrarySelection.current = libraryServerId;
  }, [availableLibraryIds, libraryServerId, libraries]);

  const targetIds = useMemo(
    () => {
      if (scope === "recent" && recentServerId === "all") {
        return servers.map((server) => server.id);
      }
      const selectedServerId = scope === "recent"
        ? recentServerId
        : libraryServerId;
      return servers.some((server) => server.id === selectedServerId)
        ? [selectedServerId]
        : [];
    },
    [libraryServerId, recentServerId, scope, servers],
  );

  async function selectRecentServer(nextServerId: string) {
    if (nextServerId === recentServerId) return true;
    if (!(await confirmDiscardRecentConfigDraft())) return false;
    setRecentServerId(nextServerId);
    persistProbeRecentServerId(nextServerId);
    return true;
  }

  async function selectLibraryServer(nextServerId: string) {
    if (nextServerId === libraryServerId) return true;
    if (!(await confirmDiscardRecentConfigDraft())) return false;
    setLibraryServerId(nextServerId);
    persistProbeLibraryServerId(nextServerId);
    return true;
  }

  return {
    libraryServerId,
    recentServerId,
    scope,
    selectedDiscoveryLibraryIds,
    selectedLibraryData,
    selectedProcessingLibraryIds,
    selectLibraryServer,
    selectRecentServer,
    setDiscoveryLibraries,
    setProcessingLibraries,
    targetIds,
  };
}

export { useProbeContextSelection };
