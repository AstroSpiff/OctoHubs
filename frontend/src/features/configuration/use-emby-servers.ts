import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { createEmbyServer, deleteEmbyServer, getEmbyServers, updateEmbyServer } from "@/features/configuration/api";
import type { EmbyServerInput } from "@/features/configuration/types";
import { useKeyedOperationState } from "@/lib/use-keyed-operation-state";
import { useSensitiveMutation } from "@/lib/use-sensitive-mutation";

function useEmbyServers() {
  const client = useQueryClient();
  const updates = useKeyedOperationState();
  const removals = useKeyedOperationState();
  const servers = useQuery({ queryKey: ["configuration", "emby-servers"], queryFn: getEmbyServers });
  const refresh = () => client.invalidateQueries({ queryKey: ["configuration", "emby-servers"] });
  const create = useSensitiveMutation({ mutationFn: createEmbyServer, onSuccess: refresh });
  const update = useSensitiveMutation({
    mutationFn: ({ serverId, input }: { serverId: string; input: EmbyServerInput }) => updateEmbyServer(serverId, input),
    onMutate: ({ serverId }) => updates.begin([serverId]),
    publicVariables: ({ serverId }) => ({ serverId }),
    onSuccess: refresh,
    onSettled: (_data, _error, variables) => updates.finish([variables.serverId]),
  });
  const remove = useMutation({
    mutationFn: deleteEmbyServer,
    onMutate: (serverId) => removals.begin([serverId]),
    onError: (error, serverId) => removals.fail([serverId], error),
    onSuccess: refresh,
    onSettled: (_data, _error, serverId) => removals.finish([serverId]),
  });

  return {
    servers,
    create,
    update,
    remove,
    refresh,
    updatingIds: updates.pendingKeys,
    deletingIds: removals.pendingKeys,
    removalErrors: removals.errors,
  };
}

export { useEmbyServers };
