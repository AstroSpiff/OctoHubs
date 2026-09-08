import { useCallback, useEffect, useRef, useState } from "react";

import type { ConfigurationTabId } from "@/features/configuration/configuration-navigation";
import { useWorkspaceCapabilities } from "@/features/session/workspace-capabilities-context";

type ConfigurationFeedbackLease = Readonly<{
  generation: number;
  targetKey: string;
}>;

type ConfigurationFeedbackEntry = ConfigurationFeedbackLease & {
  error: string;
  notice: string;
};

function useConfigurationFeedback(activeTab: ConfigurationTabId) {
  const { accountId } = useWorkspaceCapabilities();
  const targetKey = `${accountId ?? "anonymous"}:${activeTab}`;
  const targetRef = useRef<ConfigurationFeedbackLease>({ generation: 0, targetKey });
  const mountedRef = useRef(false);
  const [entry, setEntry] = useState<ConfigurationFeedbackEntry | null>(null);

  if (targetRef.current.targetKey !== targetKey) {
    targetRef.current = {
      generation: targetRef.current.generation + 1,
      targetKey,
    };
  }

  const begin = useCallback((): ConfigurationFeedbackLease | null => {
    const current = targetRef.current;
    if (!mountedRef.current || current.targetKey !== targetKey) return null;
    const next = {
      generation: current.generation + 1,
      targetKey,
    };
    targetRef.current = next;
    setEntry(null);
    return next;
  }, [targetKey]);

  const publish = useCallback((
    lease: ConfigurationFeedbackLease,
    value: Pick<ConfigurationFeedbackEntry, "error" | "notice">,
  ) => {
    const current = targetRef.current;
    if (
      !mountedRef.current
      || current.targetKey !== lease.targetKey
      || current.generation !== lease.generation
    ) return false;
    setEntry({ ...lease, ...value });
    return true;
  }, []);

  const clear = useCallback(() => {
    const current = targetRef.current;
    if (!mountedRef.current || current.targetKey !== targetKey) return;
    targetRef.current = {
      generation: current.generation + 1,
      targetKey,
    };
    setEntry(null);
  }, [targetKey]);

  const publishImmediateNotice = useCallback((notice: string) => {
    const current = targetRef.current;
    if (!mountedRef.current || current.targetKey !== targetKey) return false;
    const lease = {
      generation: current.generation + 1,
      targetKey,
    };
    targetRef.current = lease;
    setEntry({ ...lease, error: "", notice });
    return true;
  }, [targetKey]);

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
    };
  }, []);

  const visible = entry?.targetKey === targetRef.current.targetKey
    && entry.generation === targetRef.current.generation
    ? entry
    : null;

  return {
    begin,
    clear,
    error: visible?.error || "",
    notice: visible?.notice || "",
    publishError: (lease: ConfigurationFeedbackLease, error: string) =>
      publish(lease, { error, notice: "" }),
    publishNotice: (lease: ConfigurationFeedbackLease, notice: string) =>
      publish(lease, { error: "", notice }),
    publishImmediateNotice,
  };
}

export { useConfigurationFeedback };
export type { ConfigurationFeedbackLease };
