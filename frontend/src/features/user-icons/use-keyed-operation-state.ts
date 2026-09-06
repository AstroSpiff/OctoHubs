import { useKeyedOperationState } from "@/lib/use-keyed-operation-state";

function iconProfileOperationKey(profileId: string) {
  return `profile:${profileId}`;
}

function iconRuleOperationKey(profileId: string, serverId: string) {
  return `rule:${profileId}:${serverId}`;
}

function iconBindingOperationKey(targetType: "group" | "user", targetId: string) {
  return `binding:${targetType}:${targetId}`;
}

export {
  iconBindingOperationKey,
  iconProfileOperationKey,
  iconRuleOperationKey,
  useKeyedOperationState,
};
