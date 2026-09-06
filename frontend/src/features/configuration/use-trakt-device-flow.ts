import { useCallback, useEffect, useRef, useState } from "react";

import {
  clearTraktDeviceFlow,
  pollTraktDeviceFlow,
  startTraktDeviceFlow,
} from "@/features/configuration/api";
import {
  createTraktDeviceAttempt,
  traktDeviceAttemptExpired,
} from "@/features/configuration/trakt-device-attempt";
import type { TraktDeviceAttempt } from "@/features/configuration/trakt-device-attempt";

type TraktDeviceFlowOptions = {
  clientId: string;
  clientSecret: string;
  disabled: boolean;
  onChanged: (message: string) => void;
};

function useTraktDeviceFlow({
  clientId,
  clientSecret,
  disabled,
  onChanged,
}: TraktDeviceFlowOptions) {
  const [attempt, setAttempt] = useState<TraktDeviceAttempt | null>(null);
  const [status, setStatus] = useState("");
  const [statusKind, setStatusKind] = useState<"status" | "error">("status");
  const [busy, setBusy] = useState(false);
  const timer = useRef<number | null>(null);
  const generation = useRef(0);
  const requestController = useRef<AbortController | null>(null);
  const mounted = useRef(true);
  const previousConfig = useRef({ clientId, clientSecret, disabled });

  const clearPolling = useCallback(() => {
    if (timer.current !== null) window.clearTimeout(timer.current);
    timer.current = null;
  }, []);

  const invalidateAttempt = useCallback(() => {
    generation.current += 1;
    clearPolling();
    requestController.current?.abort();
    requestController.current = null;
    return generation.current;
  }, [clearPolling]);

  function isCurrent(attemptGeneration: number) {
    return mounted.current && generation.current === attemptGeneration;
  }

  function beginRequest(attemptGeneration: number) {
    if (!isCurrent(attemptGeneration)) return null;
    const controller = new AbortController();
    requestController.current = controller;
    return controller;
  }

  function releaseRequest(controller: AbortController) {
    if (requestController.current === controller) requestController.current = null;
  }

  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
      invalidateAttempt();
    };
  }, [invalidateAttempt]);

  useEffect(() => {
    const previous = previousConfig.current;
    if (
      previous.clientId === clientId
      && previous.clientSecret === clientSecret
      && previous.disabled === disabled
    ) return;
    previousConfig.current = { clientId, clientSecret, disabled };
    invalidateAttempt();
    setAttempt(null);
    setBusy(false);
    setStatus("Configurazione Trakt cambiata. Avvia un nuovo collegamento.");
    setStatusKind("error");
  }, [clientId, clientSecret, disabled, invalidateAttempt]);

  async function connect() {
    if (!clientId.trim()) {
      setStatus("Inserisci il Client ID per collegare Trakt.");
      setStatusKind("error");
      return;
    }

    const attemptGeneration = invalidateAttempt();
    const controller = beginRequest(attemptGeneration);
    if (!controller) return;
    setBusy(true);
    setStatus("");
    setStatusKind("status");
    try {
      const next = await startTraktDeviceFlow(clientId, controller.signal);
      if (!isCurrent(attemptGeneration) || controller.signal.aborted) return;
      const nextAttempt = createTraktDeviceAttempt(
        next,
        clientId.trim(),
        clientSecret,
        Date.now(),
      );
      setAttempt(nextAttempt);
      setStatus("Apri Trakt e inserisci il codice indicato.");
      setStatusKind("status");
      schedulePoll(nextAttempt, attemptGeneration);
    } catch (error) {
      if (!isCurrent(attemptGeneration) || controller.signal.aborted) return;
      invalidateAttempt();
      setAttempt(null);
      setStatus(error instanceof Error ? error.message : "Impossibile avviare Trakt.");
      setStatusKind("error");
      setBusy(false);
    } finally {
      releaseRequest(controller);
    }
  }

  function expireAttempt(attemptGeneration: number) {
    if (!isCurrent(attemptGeneration)) return;
    invalidateAttempt();
    setAttempt(null);
    setBusy(false);
    setStatus("Codice Trakt scaduto. Riprova.");
    setStatusKind("error");
  }

  function schedulePoll(
    current: TraktDeviceAttempt,
    attemptGeneration: number,
  ) {
    if (!isCurrent(attemptGeneration)) return;
    if (traktDeviceAttemptExpired(current, Date.now())) {
      expireAttempt(attemptGeneration);
      return;
    }
    const delay = Math.max(2, current.device.interval || 5) * 1_000;
    timer.current = window.setTimeout(
      () => void poll(current, attemptGeneration),
      delay,
    );
  }

  async function poll(
    current: TraktDeviceAttempt,
    attemptGeneration: number,
  ) {
    if (!isCurrent(attemptGeneration)) return;
    if (traktDeviceAttemptExpired(current, Date.now())) {
      expireAttempt(attemptGeneration);
      return;
    }
    const controller = beginRequest(attemptGeneration);
    if (!controller) return;
    try {
      const result = await pollTraktDeviceFlow(
        current.clientId,
        current.clientSecret,
        current.device.device_code,
        current.device.config_revision,
        controller.signal,
      );
      if (!isCurrent(attemptGeneration) || controller.signal.aborted) return;
      if (result.status === "authorized") {
        invalidateAttempt();
        setAttempt(null);
        setBusy(false);
        setStatus("");
        setStatusKind("status");
        onChanged("Trakt collegato.");
        return;
      }
      schedulePoll(current, attemptGeneration);
    } catch (error) {
      if (!isCurrent(attemptGeneration) || controller.signal.aborted) return;
      invalidateAttempt();
      setBusy(false);
      setAttempt(null);
      setStatus(error instanceof Error ? error.message : "Collegamento Trakt non riuscito.");
      setStatusKind("error");
    } finally {
      releaseRequest(controller);
    }
  }

  async function disconnect() {
    const attemptGeneration = invalidateAttempt();
    const controller = beginRequest(attemptGeneration);
    if (!controller) return;
    setAttempt(null);
    setBusy(true);
    setStatus("");
    setStatusKind("status");
    try {
      const result = await clearTraktDeviceFlow(controller.signal);
      if (!isCurrent(attemptGeneration) || controller.signal.aborted) return;
      onChanged(result.message);
    } catch (error) {
      if (!isCurrent(attemptGeneration) || controller.signal.aborted) return;
      setStatus(error instanceof Error ? error.message : "Impossibile scollegare Trakt.");
      setStatusKind("error");
    } finally {
      releaseRequest(controller);
      if (isCurrent(attemptGeneration)) setBusy(false);
    }
  }

  function cancel() {
    invalidateAttempt();
    setAttempt(null);
    setBusy(false);
    setStatus("Collegamento Trakt annullato.");
    setStatusKind("status");
  }

  return {
    attempt,
    busy,
    cancel,
    connect,
    disconnect,
    status,
    statusKind,
  };
}

export { useTraktDeviceFlow };
