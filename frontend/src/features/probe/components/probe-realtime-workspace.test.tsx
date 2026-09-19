// @vitest-environment jsdom

import { act } from "react";
import type { ReactNode } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { EmbyLiveSnapshot } from "@/features/emby-live/types";
import { ProbeRealtimeWorkspace } from "@/features/probe/components/probe-realtime-workspace";

vi.mock("@/components/ui/query-state-boundary", () => ({
  QueryStateBoundary: ({ children }: { children: ReactNode }) => children,
}));

vi.mock("@/features/probe/components/probe-workspace", () => ({
  ProbeWorkspace: ({ children }: { children: ReactNode }) => (
    <section>{children}</section>
  ),
}));

vi.mock("@/features/probe/components/library-probe-controls", () => ({
  LibraryProbeControls: ({ processingStatus }: {
    processingStatus?: { processed?: number };
  }) => <p>Processati {processingStatus?.processed || 0}</p>,
}));

vi.mock("@/features/probe/components/recent-probe-controls", () => ({
  RecentProbeControls: () => null,
}));

declare global {
  var IS_REACT_ACT_ENVIRONMENT: boolean | undefined;
}

class FakeEventSource {
  static instances: FakeEventSource[] = [];

  onerror: (() => void) | null = null;
  onmessage: ((event: { data: string }) => void) | null = null;
  onopen: (() => void) | null = null;

  constructor(readonly url: string) {
    FakeEventSource.instances.push(this);
  }

  close() {}
}

function snapshot(processed: number): EmbyLiveSnapshot {
  return {
    success: true,
    servers: {
      "server-a": {
        server: { id: "server-a", name: "Black", enabled: true },
        status: { ok: true },
        running_tasks: [],
        tasks_error: null,
        streams: [],
        streams_error: null,
        probe_status: {
          processing: { running: true, processed, total: 100 },
        },
      },
    },
  };
}

describe("ProbeRealtimeWorkspace", () => {
  let container: HTMLDivElement;
  let root: ReturnType<typeof createRoot>;

  beforeEach(() => {
    globalThis.IS_REACT_ACT_ENVIRONMENT = true;
    FakeEventSource.instances = [];
    vi.stubGlobal("EventSource", FakeEventSource);
    container = document.createElement("div");
    document.body.append(container);
    root = createRoot(container);
  });

  afterEach(() => {
    act(() => root.unmount());
    container.remove();
    globalThis.IS_REACT_ACT_ENVIRONMENT = undefined;
    vi.unstubAllGlobals();
    vi.resetAllMocks();
  });

  it("aggiorna i worker realtime senza ridisegnare la regione dati adiacente", () => {
    let dataRegionRenders = 0;
    const onServersChange = vi.fn();
    const noop = vi.fn();

    function DataRegion() {
      dataRegionRenders += 1;
      return <div>Storico pesante</div>;
    }

    function Harness() {
      return (
        <>
          <ProbeRealtimeWorkspace
            scope="libraries"
            serverId="server-a"
            targetIds={["server-a"]}
            libraries={[]}
            discoverySelected={[]}
            processingSelected={[]}
            busy={false}
            librariesFetching={false}
            canMutate
            refreshRequest={0}
            onServersChange={onServersChange}
            onServerChange={noop}
            onDiscoverySelectionChange={noop}
            onProcessingSelectionChange={noop}
            onRunCombo={noop}
            onStopCombo={noop}
            onRunDiscovery={noop}
            onStopDiscovery={noop}
            onRunProcessing={noop}
            onStopProcessing={noop}
          />
          <DataRegion />
        </>
      );
    }

    act(() => root.render(<Harness />));
    const source = FakeEventSource.instances[0];

    act(() => source.onmessage?.({ data: JSON.stringify(snapshot(1)) }));
    expect(container.textContent).toContain("Processati 1");
    expect(dataRegionRenders).toBe(1);
    expect(onServersChange).toHaveBeenCalledOnce();

    act(() => source.onmessage?.({ data: JSON.stringify(snapshot(2)) }));
    expect(container.textContent).toContain("Processati 2");
    expect(dataRegionRenders).toBe(1);
    expect(onServersChange).toHaveBeenCalledOnce();
  });
});
