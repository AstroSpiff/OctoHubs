// @vitest-environment jsdom

import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  type ApplicationEvent,
  useApplicationEventRefresh,
} from "@/lib/use-application-event";

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

  emit(event: ApplicationEvent) {
    this.onmessage?.(new MessageEvent("message", { data: JSON.stringify(event) }));
  }
}

function EventHarness({ onRefresh }: { onRefresh: (event: ApplicationEvent) => void }) {
  useApplicationEventRefresh(
    (event) => event.MessageType === "OctoHubsConfigurationUpdated",
    onRefresh,
  );
  return null;
}

describe("useApplicationEventRefresh", () => {
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

  it("flushes every relevant event received during one debounce window", () => {
    const onRefresh = vi.fn();
    act(() => root.render(<EventHarness onRefresh={onRefresh} />));
    const source = EventSourceStub.instances[0];

    act(() => {
      source.emit({
        MessageType: "OctoHubsConfigurationUpdated",
        Data: { scope: "servers" },
      });
      source.emit({
        MessageType: "OctoHubsConfigurationUpdated",
        Data: { scope: "telegram" },
      });
      vi.advanceTimersByTime(350);
    });

    expect(onRefresh).toHaveBeenCalledTimes(2);
    expect(onRefresh.mock.calls.map(([event]) => event.Data)).toEqual([
      { scope: "servers" },
      { scope: "telegram" },
    ]);
  });

  it("shares one EventSource across all document subscribers", () => {
    const firstRefresh = vi.fn();
    const secondRefresh = vi.fn();
    act(() => {
      root.render(
        <>
          <EventHarness onRefresh={firstRefresh} />
          <EventHarness onRefresh={secondRefresh} />
        </>,
      );
    });

    expect(EventSourceStub.instances).toHaveLength(1);
    act(() => {
      EventSourceStub.instances[0].emit({
        MessageType: "OctoHubsConfigurationUpdated",
        Data: { scope: "servers" },
      });
      vi.advanceTimersByTime(350);
    });

    expect(firstRefresh).toHaveBeenCalledOnce();
    expect(secondRefresh).toHaveBeenCalledOnce();
  });

  it("refreshes periodically under continuous traffic and deduplicates one target", () => {
    const onRefresh = vi.fn();
    act(() => root.render(<EventHarness onRefresh={onRefresh} />));
    const source = EventSourceStub.instances[0];

    act(() => {
      for (let index = 0; index < 10; index += 1) {
        source.emit({
          MessageType: "OctoHubsConfigurationUpdated",
          Data: { scope: "servers", sequence: index },
        });
        vi.advanceTimersByTime(100);
      }
    });

    expect(onRefresh).toHaveBeenCalledTimes(2);
    act(() => vi.advanceTimersByTime(350));
    expect(onRefresh).toHaveBeenCalledTimes(3);
  });

  it("bounds a burst while retaining the newest distinct targets", () => {
    const onRefresh = vi.fn();
    act(() => root.render(<EventHarness onRefresh={onRefresh} />));
    const source = EventSourceStub.instances[0];

    act(() => {
      for (let index = 0; index < 100; index += 1) {
        source.emit({
          MessageType: "OctoHubsConfigurationUpdated",
          Data: { scope: `scope-${index}` },
        });
      }
      vi.advanceTimersByTime(350);
    });

    expect(onRefresh).toHaveBeenCalledTimes(64);
    expect(onRefresh.mock.calls[0][0].Data).toEqual({ scope: "scope-36" });
    expect(onRefresh.mock.calls.at(-1)?.[0].Data).toEqual({ scope: "scope-99" });
  });
});
