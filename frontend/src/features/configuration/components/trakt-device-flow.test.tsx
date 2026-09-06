// @vitest-environment jsdom

import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  pollTraktDeviceFlow,
  startTraktDeviceFlow,
} from "@/features/configuration/api";
import { TraktDeviceFlow } from "@/features/configuration/components/trakt-device-flow";
import type {
  TraktDevicePoll,
  TraktDeviceStart,
} from "@/features/configuration/types";


vi.mock("@/features/configuration/api", () => ({
  clearTraktDeviceFlow: vi.fn(),
  pollTraktDeviceFlow: vi.fn(),
  startTraktDeviceFlow: vi.fn(),
}));

declare global {
  var IS_REACT_ACT_ENVIRONMENT: boolean | undefined;
}

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((complete) => {
    resolve = complete;
  });
  return { promise, resolve };
}

function device(code: string, interval = 2): TraktDeviceStart {
  return {
    success: true,
    device_code: `device-${code}`,
    user_code: code,
    verification_url: "https://trakt.tv/activate",
    expires_in: 600,
    interval,
    config_revision: `revision-${code}`,
  };
}

describe("TraktDeviceFlow lifecycle", () => {
  let container: HTMLDivElement;
  let root: ReturnType<typeof createRoot>;
  let onChanged: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    globalThis.IS_REACT_ACT_ENVIRONMENT = true;
    vi.useFakeTimers();
    onChanged = vi.fn();
    container = document.createElement("div");
    document.body.appendChild(container);
    root = createRoot(container);
    act(() => {
      root.render(
        <TraktDeviceFlow
          clientId="client-id"
          clientSecret="client-secret"
          connected={false}
          expiresAt=""
          disabled={false}
          onChanged={onChanged}
        />,
      );
    });
  });

  afterEach(() => {
    act(() => root.unmount());
    container.remove();
    vi.useRealTimers();
    vi.resetAllMocks();
    globalThis.IS_REACT_ACT_ENVIRONMENT = undefined;
  });

  it("aborts and ignores an in-flight poll after cancellation", async () => {
    const pollResult = deferred<TraktDevicePoll>();
    vi.mocked(startTraktDeviceFlow).mockResolvedValue(device("FIRST"));
    vi.mocked(pollTraktDeviceFlow).mockReturnValue(pollResult.promise);

    await connectAndStartPolling(container);
    const signal = vi.mocked(pollTraktDeviceFlow).mock.calls[0][4];

    act(() => clickButton(container, "Annulla collegamento"));
    expect(signal?.aborted).toBe(true);
    expect(container.textContent).toContain("Collegamento Trakt annullato.");

    await act(async () => {
      pollResult.resolve({ status: "authorized" });
      await pollResult.promise;
      await Promise.resolve();
    });

    expect(onChanged).not.toHaveBeenCalled();
    expect(container.textContent).not.toContain("FIRST");
    expect(vi.getTimerCount()).toBe(0);
  });

  it("aborts and ignores an in-flight poll when the component unmounts", async () => {
    const pollResult = deferred<TraktDevicePoll>();
    vi.mocked(startTraktDeviceFlow).mockResolvedValue(device("FIRST"));
    vi.mocked(pollTraktDeviceFlow).mockReturnValue(pollResult.promise);

    await connectAndStartPolling(container);
    const signal = vi.mocked(pollTraktDeviceFlow).mock.calls[0][4];

    act(() => root.render(<></>));
    expect(signal?.aborted).toBe(true);

    await act(async () => {
      pollResult.resolve({ status: "authorized" });
      await pollResult.promise;
      await Promise.resolve();
    });

    expect(onChanged).not.toHaveBeenCalled();
    expect(container.textContent).toBe("");
    expect(vi.getTimerCount()).toBe(0);
  });

  it("keeps a newer attempt active when an older poll completes", async () => {
    const oldPoll = deferred<TraktDevicePoll>();
    vi.mocked(startTraktDeviceFlow)
      .mockResolvedValueOnce(device("FIRST"))
      .mockResolvedValueOnce(device("SECOND", 10));
    vi.mocked(pollTraktDeviceFlow).mockReturnValueOnce(oldPoll.promise);

    await connectAndStartPolling(container);
    const oldSignal = vi.mocked(pollTraktDeviceFlow).mock.calls[0][4];
    act(() => clickButton(container, "Annulla collegamento"));
    await act(async () => {
      clickButton(container, "Collega Trakt");
      await Promise.resolve();
      await Promise.resolve();
    });

    expect(oldSignal?.aborted).toBe(true);
    expect(container.textContent).toContain("SECOND");
    expect(vi.getTimerCount()).toBe(1);

    await act(async () => {
      oldPoll.resolve({ status: "authorized" });
      await oldPoll.promise;
      await Promise.resolve();
    });

    expect(onChanged).not.toHaveBeenCalled();
    expect(container.textContent).toContain("SECOND");
    expect(vi.getTimerCount()).toBe(1);
  });

  it("invalidates an in-flight attempt when OAuth inputs change", async () => {
    const pollResult = deferred<TraktDevicePoll>();
    vi.mocked(startTraktDeviceFlow).mockResolvedValue(device("FIRST"));
    vi.mocked(pollTraktDeviceFlow).mockReturnValue(pollResult.promise);

    await connectAndStartPolling(container);
    const signal = vi.mocked(pollTraktDeviceFlow).mock.calls[0][4];
    act(() => {
      root.render(
        <TraktDeviceFlow
          clientId="replacement-client"
          clientSecret="replacement-secret"
          connected={false}
          expiresAt=""
          disabled={false}
          onChanged={onChanged}
        />,
      );
    });

    expect(signal?.aborted).toBe(true);
    expect(container.textContent).not.toContain("FIRST");
    expect(container.querySelector('[role="alert"]')?.textContent).toContain(
      "Configurazione Trakt cambiata",
    );

    await act(async () => {
      pollResult.resolve({ status: "authorized" });
      await pollResult.promise;
    });
    expect(onChanged).not.toHaveBeenCalled();
  });

  it("announces a ready device code through the persistent status region", async () => {
    vi.mocked(startTraktDeviceFlow).mockResolvedValue(device("READY"));

    await act(async () => {
      clickButton(container, "Collega Trakt");
      await Promise.resolve();
      await Promise.resolve();
    });

    const status = container.querySelector('[role="status"]');
    expect(status?.getAttribute("aria-live")).toBe("polite");
    expect(status?.textContent).toContain("READY");
    expect(status?.querySelector("strong")?.getAttribute("aria-label")).toBe(
      "Codice Trakt READY",
    );
  });
});

async function connectAndStartPolling(container: HTMLDivElement) {
  await act(async () => {
    clickButton(container, "Collega Trakt");
    await Promise.resolve();
    await Promise.resolve();
  });
  await act(async () => {
    await vi.advanceTimersByTimeAsync(2_000);
  });
  expect(pollTraktDeviceFlow).toHaveBeenCalledOnce();
}

function clickButton(container: HTMLDivElement, label: string) {
  const button = [...container.querySelectorAll<HTMLButtonElement>("button")]
    .find((candidate) => candidate.textContent?.trim() === label);
  expect(button).toBeDefined();
  button?.click();
}
