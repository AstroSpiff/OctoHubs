// @vitest-environment jsdom

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  getTranscodeGuardSettings,
  saveTranscodeGuardSettings,
} from "@/features/transcode-guard-settings/api";
import { createGuardRule } from "@/features/transcode-guard-settings/rule-model";
import type {
  GuardSettingsResponse,
  GuardSettingsSaveResult,
  TranscodeGuardSettings,
} from "@/features/transcode-guard-settings/types";
import { useTranscodeGuardSettings } from "@/features/transcode-guard-settings/use-transcode-guard-settings";

vi.mock("@/features/transcode-guard-settings/api", () => ({
  getTranscodeGuardSettings: vi.fn(),
  saveTranscodeGuardSettings: vi.fn(),
}));

declare global {
  var IS_REACT_ACT_ENVIRONMENT: boolean | undefined;
}

type Deferred<T> = {
  promise: Promise<T>;
  resolve: (value: T) => void;
};

function deferred<T>(): Deferred<T> {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((complete) => {
    resolve = complete;
  });
  return { promise, resolve };
}

function settings(pollIntervalSeconds: number): TranscodeGuardSettings {
  return {
    enabled: true,
    poll_interval_seconds: pollIntervalSeconds,
    stream_history_retention_days: 30,
    rules: [createGuardRule()],
  };
}

let latestSettings: ReturnType<typeof useTranscodeGuardSettings> | undefined;

function GuardSettingsHarness() {
  latestSettings = useTranscodeGuardSettings();
  return null;
}

async function waitForDraft() {
  for (let attempt = 0; attempt < 10; attempt += 1) {
    await act(async () => {
      await new Promise((resolve) => window.setTimeout(resolve, 0));
    });
    if (latestSettings?.draft) return;
  }
  throw new Error("La configurazione Transcode Guard non e' stata caricata");
}

describe("useTranscodeGuardSettings", () => {
  let container: HTMLDivElement;
  let root: ReturnType<typeof createRoot>;
  let queryClient: QueryClient;

  beforeEach(() => {
    globalThis.IS_REACT_ACT_ENVIRONMENT = true;
    latestSettings = undefined;
    queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
    container = document.createElement("div");
    document.body.append(container);
    root = createRoot(container);
  });

  afterEach(() => {
    act(() => root.unmount());
    queryClient.clear();
    container.remove();
    globalThis.IS_REACT_ACT_ENVIRONMENT = undefined;
    vi.clearAllMocks();
  });

  it("keeps an unsaved newer draft when an earlier settings save resolves", async () => {
    const saveResult = deferred<GuardSettingsSaveResult>();
    const initial: GuardSettingsResponse = {
      ok: true,
      settings: settings(10),
      servers: [],
    };
    vi.mocked(getTranscodeGuardSettings).mockResolvedValue(initial);
    vi.mocked(saveTranscodeGuardSettings).mockReturnValue(saveResult.promise);

    await act(async () => {
      root.render(
        <QueryClientProvider client={queryClient}>
          <GuardSettingsHarness />
        </QueryClientProvider>,
      );
    });
    await waitForDraft();

    const submitted = settings(15);
    act(() => {
      latestSettings?.updateDraft(() => submitted);
      latestSettings?.save.mutate(submitted);
      latestSettings?.updateDraft((current) => ({
        ...current,
        poll_interval_seconds: 20,
      }));
    });

    await act(async () => {
      saveResult.resolve({ ok: true, settings: submitted });
      await saveResult.promise;
      await new Promise((resolve) => window.setTimeout(resolve, 0));
    });

    expect(latestSettings?.dirty).toBe(true);
    expect(latestSettings?.draft?.poll_interval_seconds).toBe(20);
  });
});
