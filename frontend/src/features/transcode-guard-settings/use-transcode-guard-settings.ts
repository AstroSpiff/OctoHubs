import { useEffect, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { getTranscodeGuardSettings, saveTranscodeGuardSettings } from "@/features/transcode-guard-settings/api";
import { transcodeGuardSettingsEqual } from "@/features/transcode-guard-settings/settings-equality";
import type { TranscodeGuardSettings } from "@/features/transcode-guard-settings/types";

export function useTranscodeGuardSettings() {
  const queryClient = useQueryClient();
  const settings = useQuery({
    queryKey: ["transcode-guard-settings"],
    queryFn: getTranscodeGuardSettings,
    refetchInterval: 10_000,
  });
  const [draft, setDraft] = useState<TranscodeGuardSettings>();
  const draftRef = useRef<TranscodeGuardSettings | undefined>(undefined);
  const [baseline, setBaseline] = useState<TranscodeGuardSettings>();
  const [notice, setNotice] = useState("");
  const dirty = Boolean(draft && baseline && !transcodeGuardSettingsEqual(draft, baseline));
  const save = useMutation({
    mutationFn: saveTranscodeGuardSettings,
    onSuccess: async (result, submittedSettings) => {
      queryClient.setQueryData(["transcode-guard-settings"], result);
      const hasNewerDraft = Boolean(
        draftRef.current
        && !transcodeGuardSettingsEqual(draftRef.current, submittedSettings),
      );
      if (!hasNewerDraft) {
        draftRef.current = result.settings;
        setDraft(result.settings);
      }
      setBaseline(result.settings);
      setNotice("Regole Transcode Guard salvate e applicate.");
      await queryClient.invalidateQueries({ queryKey: ["transcode-guard-settings"] });
      await queryClient.invalidateQueries({ queryKey: ["transcode-guard-status"] });
    },
  });

  useEffect(() => {
    if (!settings.data?.settings || dirty) return;
    draftRef.current = settings.data.settings;
    setBaseline(settings.data.settings);
    setDraft(settings.data.settings);
  }, [dirty, settings.data?.settings]);

  function updateDraft(updater: (current: TranscodeGuardSettings) => TranscodeGuardSettings) {
    setDraft((current) => {
      if (!current) return current;
      const next = updater(current);
      draftRef.current = next;
      return next;
    });
    setNotice("");
  }

  return { settings, draft, dirty, notice, save, updateDraft };
}
