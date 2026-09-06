import { useCallback, useEffect, useRef, useState } from "react";

import { getSystemStatus } from "@/features/system-status/api";
import {
  isSystemStatusRealtimeEvent,
  systemStatusRefreshDelayMs,
  systemStatusSectionsForEvent,
} from "@/features/system-status/realtime";
import type { SystemSection } from "@/features/system-status/types";
import { useApplicationEventRefresh } from "@/lib/use-application-event";

const refreshScanIntervalMs = 1_000;

export function useSystemStatus() {
  const [sections, setSections] = useState<SystemSection[]>([]);
  const [generatedAt, setGeneratedAt] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [sectionErrors, setSectionErrors] = useState<Record<string, string>>({});
  const [refreshingSections, setRefreshingSections] = useState<Set<string>>(
    () => new Set(),
  );
  const sectionsRef = useRef<SystemSection[]>([]);
  const nextRefreshRef = useRef<Record<string, number>>({});
  const refreshingRef = useRef<Set<string>>(new Set());
  const fullRefreshRunningRef = useRef(false);
  const snapshotVersionRef = useRef(0);
  const dataVersionRef = useRef(0);

  useEffect(() => {
    sectionsRef.current = sections;
  }, [sections]);

  const mergeSection = useCallback((section: SystemSection, updatedAt = "") => {
    const current = sectionsRef.current;
    const index = current.findIndex((item) => item.id === section.id);
    const next = index === -1
      ? [...current, section]
      : current.map((item, itemIndex) => (itemIndex === index ? section : item));
    sectionsRef.current = next;
    setSections(next);
    if (updatedAt) setGeneratedAt(updatedAt);
  }, []);

  const setSectionRefreshing = useCallback((sectionId: string, refreshing: boolean) => {
    const next = new Set(refreshingRef.current);
    if (refreshing) {
      next.add(sectionId);
    } else {
      next.delete(sectionId);
    }
    refreshingRef.current = next;
    setRefreshingSections(next);
  }, []);

  const setSectionError = useCallback((sectionId: string, message = "") => {
    setSectionErrors((current) => {
      if (!message && !current[sectionId]) return current;
      const next = { ...current };
      if (message) {
        next[sectionId] = message;
      } else {
        delete next[sectionId];
      }
      return next;
    });
  }, []);

  const refreshAll = useCallback(async () => {
    if (fullRefreshRunningRef.current) return;
    fullRefreshRunningRef.current = true;
    const dataVersion = dataVersionRef.current;
    setLoading(true);
    setError("");
    try {
      const payload = await getSystemStatus();
      if (dataVersion !== dataVersionRef.current) return;
      const now = Date.now();
      snapshotVersionRef.current += 1;
      dataVersionRef.current += 1;
      sectionsRef.current = payload.sections;
      setSections(payload.sections);
      setSectionErrors({});
      setGeneratedAt(payload.generated_at);
      nextRefreshRef.current = Object.fromEntries(
        payload.sections.flatMap((section) => {
          const delay = systemStatusRefreshDelayMs(section.refresh_interval_seconds);
          return delay === null ? [] : [[section.id, now + delay]];
        }),
      );
    } catch (requestError) {
      if (dataVersion === dataVersionRef.current) {
        setError(requestError instanceof Error ? requestError.message : "Impossibile leggere lo stato del sistema");
      }
    } finally {
      fullRefreshRunningRef.current = false;
      setLoading(false);
    }
  }, []);

  const refreshSection = useCallback(async (sectionId: string, checkServices = false) => {
    if (refreshingRef.current.has(sectionId)) return;
    setSectionRefreshing(sectionId, true);
    setSectionError(sectionId);
    const snapshotVersion = snapshotVersionRef.current;
    try {
      const payload = await getSystemStatus(sectionId, checkServices);
      const section = payload.section || payload.sections[0];
      if (!section) throw new Error("La sezione richiesta non e' disponibile");
      if (snapshotVersion === snapshotVersionRef.current) {
        mergeSection(section, payload.generated_at);
        dataVersionRef.current += 1;
        const delay = systemStatusRefreshDelayMs(section.refresh_interval_seconds);
        if (delay === null) {
          delete nextRefreshRef.current[sectionId];
        } else {
          nextRefreshRef.current[sectionId] = Date.now() + delay;
        }
      }
    } catch (requestError) {
      if (snapshotVersion === snapshotVersionRef.current) {
        setSectionError(
          sectionId,
          requestError instanceof Error ? requestError.message : "Impossibile aggiornare questa area",
        );
      }
    } finally {
      setSectionRefreshing(sectionId, false);
    }
  }, [mergeSection, setSectionError, setSectionRefreshing]);

  const refreshFromRealtimeEvent = useCallback((event: Parameters<typeof systemStatusSectionsForEvent>[0]) => {
    systemStatusSectionsForEvent(event).forEach((sectionId) => {
      void refreshSection(sectionId);
    });
  }, [refreshSection]);

  useApplicationEventRefresh(
    isSystemStatusRealtimeEvent,
    refreshFromRealtimeEvent,
  );

  useEffect(() => {
    void refreshAll();
  }, [refreshAll]);

  useEffect(() => {
    const timer = window.setInterval(() => {
      if (document.visibilityState === "hidden") return;
      const now = Date.now();
      sectionsRef.current.forEach((section) => {
        if (systemStatusRefreshDelayMs(section.refresh_interval_seconds) === null) return;
        const dueAt = nextRefreshRef.current[section.id] || now;
        if (now >= dueAt && !refreshingRef.current.has(section.id)) {
          void refreshSection(section.id);
        }
      });
    }, refreshScanIntervalMs);
    return () => window.clearInterval(timer);
  }, [refreshSection]);

  return {
    sections,
    generatedAt,
    loading,
    error,
    sectionErrors,
    refreshingSections,
    refreshAll,
    refreshSection,
  };
}
