// @vitest-environment jsdom

import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { useLibrariesRealtime } from "@/features/libraries/use-libraries-realtime";

declare global {
  var IS_REACT_ACT_ENVIRONMENT: boolean | undefined;
}

class EventSourceStub {
  static instances: EventSourceStub[] = [];

  onmessage: ((message: MessageEvent<string>) => void) | null = null;
  close = vi.fn();

  constructor(readonly url: string | URL) {
    EventSourceStub.instances.push(this);
  }

  emit(message: Record<string, unknown>) {
    this.onmessage?.(
      new MessageEvent("message", { data: JSON.stringify(message) }),
    );
  }
}

function LibrariesRealtimeHarness({
  onConfigurationChange,
  onScanChange,
}: {
  onConfigurationChange: () => void;
  onScanChange: () => void;
}) {
  useLibrariesRealtime([], {
    onConfigurationChange,
    onLibraryChange: vi.fn(),
    onScanChange,
  });
  return null;
}

describe("useLibrariesRealtime scheduling", () => {
  let container: HTMLDivElement;
  let root: ReturnType<typeof createRoot>;

  beforeEach(() => {
    globalThis.IS_REACT_ACT_ENVIRONMENT = true;
    vi.useFakeTimers();
    EventSourceStub.instances = [];
    vi.stubGlobal("EventSource", EventSourceStub);
    container = document.createElement("div");
    document.body.append(container);
    root = createRoot(container);
  });

  afterEach(() => {
    act(() => root.unmount());
    container.remove();
    vi.unstubAllGlobals();
    vi.useRealTimers();
    globalThis.IS_REACT_ACT_ENVIRONMENT = undefined;
  });

  it("flushes periodically under continuous progress without starving configuration", () => {
    const onConfigurationChange = vi.fn();
    const onScanChange = vi.fn();
    act(() => {
      root.render(
        <LibrariesRealtimeHarness
          onConfigurationChange={onConfigurationChange}
          onScanChange={onScanChange}
        />,
      );
    });
    const source = EventSourceStub.instances[0];

    act(() => {
      source.emit({
        MessageType: "OctoHubsLibrariesUpdated",
        Data: { scope: "associations" },
      });
      for (let index = 0; index < 10; index += 1) {
        source.emit({ MessageType: "RefreshProgress", sequence: index });
        vi.advanceTimersByTime(100);
      }
    });

    expect(onConfigurationChange).toHaveBeenCalledOnce();
    expect(onScanChange).toHaveBeenCalledTimes(2);
    act(() => vi.advanceTimersByTime(350));
    expect(onScanChange).toHaveBeenCalledTimes(3);
  });
});
