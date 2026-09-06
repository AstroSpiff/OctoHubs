import { useCallback } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { deleteIconProfile, deleteIconRule, getUserIconConfig, saveIconBinding, saveIconProfile, uploadIconRule } from "@/features/user-icons/api";
import { isUserIconsRealtimeEvent } from "@/features/user-icons/user-icons-realtime";
import {
  iconBindingOperationKey,
  iconProfileOperationKey,
  iconRuleOperationKey,
  useKeyedOperationState,
} from "@/features/user-icons/use-keyed-operation-state";
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
  const profileOperations = useKeyedOperationState();
  const ruleOperations = useKeyedOperationState();
  const bindingOperations = useKeyedOperationState();
  useApplicationEventRefresh(isUserIconsRealtimeEvent, refreshFromRealtime);

  const profile = useMutation({
    mutationFn: saveIconProfile,
    onMutate: async (input) => {
      if (input.id) profileOperations.begin([iconProfileOperationKey(input.id)]);
      await prepareMutation();
    },
    onError: (error, input) => {
      if (input.id) profileOperations.fail([iconProfileOperationKey(input.id)], error);
    },
    onSettled: async (_data, _error, input) => {
      if (input.id) profileOperations.finish([iconProfileOperationKey(input.id)]);
      await refresh();
    },
  });
  const removeProfile = useMutation({
    mutationFn: deleteIconProfile,
    onMutate: async (profileId) => {
      profileOperations.begin([iconProfileOperationKey(profileId)]);
      await prepareMutation();
    },
    onError: (error, profileId) => profileOperations.fail([iconProfileOperationKey(profileId)], error),
    onSettled: async (_data, _error, profileId) => {
      profileOperations.finish([iconProfileOperationKey(profileId)]);
      await refresh();
    },
  });
  const binding = useMutation({
    mutationFn: saveIconBinding,
    onMutate: async (input) => {
      bindingOperations.begin([iconBindingOperationKey(input.targetType, input.targetId)]);
      await prepareMutation();
    },
    onError: (error, input) => bindingOperations.fail([iconBindingOperationKey(input.targetType, input.targetId)], error),
    onSettled: async (_data, _error, input) => {
      bindingOperations.finish([iconBindingOperationKey(input.targetType, input.targetId)]);
      await refresh();
    },
  });
  const bindings = useMutation({
    mutationFn: saveIconBindings,
    onMutate: async (inputs) => {
      bindingOperations.begin(bindingOperationKeys(inputs));
      await prepareMutation();
    },
    onError: (error, inputs) => {
      const failedInputs = error instanceof IconBindingsPartialError ? error.failedInputs : inputs;
      bindingOperations.fail(bindingOperationKeys(failedInputs), error);
    },
    onSettled: async (_data, _error, inputs) => {
      bindingOperations.finish(bindingOperationKeys(inputs));
      await refresh();
    },
  });
  const rule = useMutation({
    mutationFn: uploadIconRule,
    onMutate: async (input) => {
      ruleOperations.begin([iconRuleOperationKey(input.profileId, input.serverId)]);
      await prepareMutation();
    },
    onError: (error, input) => ruleOperations.fail([iconRuleOperationKey(input.profileId, input.serverId)], error),
    onSettled: async (_data, _error, input) => {
      ruleOperations.finish([iconRuleOperationKey(input.profileId, input.serverId)]);
      await refresh();
    },
  });
  const removeRule = useMutation({
    mutationFn: deleteIconRule,
    onMutate: async (input) => {
      ruleOperations.begin([iconRuleOperationKey(input.profileId, input.serverId)]);
      await prepareMutation();
    },
    onError: (error, input) => ruleOperations.fail([iconRuleOperationKey(input.profileId, input.serverId)], error),
    onSettled: async (_data, _error, input) => {
      ruleOperations.finish([iconRuleOperationKey(input.profileId, input.serverId)]);
      await refresh();
    },
  });

  return {
    binding,
    bindingOperations,
    bindings,
    config,
    profile,
    profileOperations,
    refresh,
    removeProfile,
    removeRule,
    rule,
    ruleOperations,
  };
}

type UserIconsController = ReturnType<typeof useUserIcons>;

async function saveIconBindings(inputs: Parameters<typeof saveIconBinding>[0][]) {
  const results = await Promise.allSettled(inputs.map((input) => saveIconBinding(input)));
  const failures = results.flatMap((result, index) =>
    result.status === "rejected" ? [{ input: inputs[index], reason: result.reason }] : [],
  );
  if (failures.length) {
    const first = failures[0].reason;
    const message = first instanceof Error ? first.message : "Errore salvataggio associazioni icona";
    throw new IconBindingsPartialError(
      failures.length === 1 ? message : `${failures.length} associazioni icona non sono state salvate: ${message}`,
      failures.map((failure) => failure.input),
    );
  }
}

class IconBindingsPartialError extends Error {
  constructor(
    message: string,
    readonly failedInputs: Parameters<typeof saveIconBinding>[0][],
  ) {
    super(message);
    this.name = "IconBindingsPartialError";
  }
}

function bindingOperationKeys(inputs: Parameters<typeof saveIconBinding>[0][]) {
  return inputs.map((input) => iconBindingOperationKey(input.targetType, input.targetId));
}

export type { UserIconsController };
export { IconBindingsPartialError, saveIconBindings, useUserIcons };
