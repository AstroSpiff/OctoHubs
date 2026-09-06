// @vitest-environment jsdom

import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { useConfirmationDialog } from "@/components/ui/use-confirmation-dialog";
import { useTranscodeGuard } from "@/features/transcode-guard/use-transcode-guard";
import { TranscodeGuardPage } from "@/pages/transcode-guard-page";

vi.mock("@/components/ui/use-confirmation-dialog", () => ({
  useConfirmationDialog: vi.fn(),
}));
vi.mock("@/features/transcode-guard/use-transcode-guard", () => ({
  useTranscodeGuard: vi.fn(),
}));
vi.mock("@/features/transcode-guard-settings/components/guard-settings-workspace", () => ({
  GuardSettingsWorkspace: () => null,
}));
vi.mock("@/features/transcode-guard/components/guard-overview", () => ({ GuardOverview: () => null }));
vi.mock("@/features/transcode-guard/components/guard-activity-list", () => ({ GuardActivityList: () => null }));
vi.mock("@/features/transcode-guard/components/guard-stream-history", () => ({ GuardStreamHistory: () => null }));

declare global {
  var IS_REACT_ACT_ENVIRONMENT: boolean | undefined;
}

describe("TranscodeGuardPage state ownership", () => {
  let container: HTMLDivElement;
  let root: ReturnType<typeof createRoot>;
  const setStateMutate = vi.fn();
  const snapshot = {
    running: true,
    active_violations: [],
    recent_events: [],
    playback_events: { rows: [] },
    stream_history: [],
    last_result: { errors: [] },
  };

  beforeEach(() => {
    globalThis.IS_REACT_ACT_ENVIRONMENT = true;
    container = document.createElement("div");
    document.body.append(container);
    root = createRoot(container);
    setStateMutate.mockReset();
  });

  afterEach(() => {
    act(() => root.unmount());
    container.remove();
    globalThis.IS_REACT_ACT_ENVIRONMENT = undefined;
    vi.clearAllMocks();
  });

  it("does not mutate after a stop confirmation when the snapshot becomes stale", async () => {
    let finishConfirmation: (accepted: boolean) => void = () => undefined;
    const confirmation = new Promise<boolean>((resolve) => {
      finishConfirmation = resolve;
    });
    vi.mocked(useConfirmationDialog).mockReturnValue({
      confirm: vi.fn(() => confirmation),
      dialog: <></>,
    });
    const state = guardHookState(snapshot);
    vi.mocked(useTranscodeGuard).mockImplementation(() => state as never);

    await renderPage(root);
    act(() => stateToggle(container).click());

    state.status.error = new Error("refresh failed");
    await renderPage(root);
    await act(async () => {
      finishConfirmation(true);
      await confirmation;
    });

    expect(setStateMutate).not.toHaveBeenCalled();
  });

  it("sends the target selected by the user when the snapshot is authoritative", async () => {
    vi.mocked(useConfirmationDialog).mockReturnValue({
      confirm: vi.fn().mockResolvedValue(true),
      dialog: <></>,
    });
    const state = guardHookState({ ...snapshot, running: false });
    vi.mocked(useTranscodeGuard).mockImplementation(() => state as never);

    await renderPage(root);
    act(() => stateToggle(container).click());

    expect(setStateMutate).toHaveBeenCalledWith("start");
  });

  function guardHookState(data: typeof snapshot) {
    const mutation = { error: null, isPending: false, mutate: vi.fn(), data: undefined };
    return {
      status: {
        data,
        error: null as Error | null,
        isFetching: false,
        isLoading: false,
        dataUpdatedAt: 1,
        refetch: vi.fn(),
      },
      checkNow: mutation,
      setState: { ...mutation, mutate: setStateMutate },
      cleanupEvents: mutation,
      cleanupStreams: mutation,
    };
  }
});

async function renderPage(root: ReturnType<typeof createRoot>) {
  await act(async () => root.render(<TranscodeGuardPage />));
}

function stateToggle(container: HTMLElement) {
  const toggle = container.querySelector<HTMLInputElement>(".guard-controls-toggle input");
  if (!toggle) throw new Error("missing Transcode Guard state toggle");
  return toggle;
}
