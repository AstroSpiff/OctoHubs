import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { createEmbyServer, deleteEmbyServer, getEmbyServers, updateEmbyServer } from "@/features/configuration/api";
import type { EmbyServerInput } from "@/features/configuration/types";
import { usePendingServerIds } from "@/features/configuration/use-pending-server-ids";

function useEmbyServers() {
  const client = useQueryClient();
  const updates = usePendingServerIds();
  const removals = usePendingServerIds();
  const servers = useQuery({ queryKey: ["configuration", "emby-servers"], queryFn: getEmbyServers });
  const refresh = () => client.invalidateQueries({ queryKey: ["configuration", "emby-servers"] });
  const create = useMutation({ mutationFn: createEmbyServer, onSuccess: refresh });
  const update = useMutation({
    mutationFn: ({ serverId, input }: { serverId: string; input: EmbyServerInput }) => updateEmbyServer(serverId, input),
    onMutate: ({ serverId }) => updates.begin(serverId),
    onSuccess: refresh,
    onSettled: (_data, _error, variables) => updates.finish(variables.serverId),
  });
  const remove = useMutation({
    mutationFn: deleteEmbyServer,
    onMutate: (serverId) => removals.begin(serverId),
    onSuccess: refresh,
    onSettled: (_data, _error, serverId) => removals.finish(serverId),
  });

  return { servers, create, update, remove, refresh, updatingIds: updates.pendingIds, deletingIds: removals.pendingIds };
}

export { useEmbyServers };
