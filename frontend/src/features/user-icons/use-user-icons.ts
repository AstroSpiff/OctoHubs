import { useCallback } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { deleteIconProfile, deleteIconRule, getUserIconConfig, saveIconBinding, saveIconProfile, uploadIconRule } from "@/features/user-icons/api";
import { isUserIconsRealtimeEvent } from "@/features/user-icons/user-icons-realtime";
import { useApplicationEventRefresh } from "@/lib/use-application-event";

function useUserIcons() {
  const client = useQueryClient();
  const config = useQuery({ queryKey: ["user-icon-config"], queryFn: getUserIconConfig, refetchInterval: 20_000 });
  const refresh = useCallback(
    () => client.invalidateQueries({ queryKey: ["user-icon-config"] }),
    [client],
  );
  const refreshFromRealtime = useCallback(() => {
    void refresh();
  }, [refresh]);
  const prepareMutation = useCallback(
    () => client.cancelQueries({ queryKey: ["user-icon-config"] }),
    [client],
  );
  useApplicationEventRefresh(isUserIconsRealtimeEvent, refreshFromRealtime);

  const profile = useMutation({ mutationFn: saveIconProfile, onMutate: prepareMutation, onSettled: refresh });
  const removeProfile = useMutation({ mutationFn: deleteIconProfile, onMutate: prepareMutation, onSettled: refresh });
  const binding = useMutation({ mutationFn: saveIconBinding, onMutate: prepareMutation, onSettled: refresh });
  const bindings = useMutation({
    mutationFn: saveIconBindings,
    onMutate: prepareMutation,
    onSettled: refresh,
  });
  const rule = useMutation({ mutationFn: uploadIconRule, onMutate: prepareMutation, onSettled: refresh });
  const removeRule = useMutation({ mutationFn: deleteIconRule, onMutate: prepareMutation, onSettled: refresh });

  return { config, profile, removeProfile, binding, bindings, rule, removeRule, refresh };
}

type UserIconsController = ReturnType<typeof useUserIcons>;

async function saveIconBindings(inputs: Parameters<typeof saveIconBinding>[0][]) {
  const results = await Promise.allSettled(inputs.map((input) => saveIconBinding(input)));
  const failures = results.filter((result): result is PromiseRejectedResult => result.status === "rejected");
  if (failures.length) {
    const first = failures[0].reason;
    const message = first instanceof Error ? first.message : "Errore salvataggio associazioni icona";
    throw new Error(failures.length === 1 ? message : `${failures.length} associazioni icona non sono state salvate: ${message}`);
  }
}

export type { UserIconsController };
export { useUserIcons };
