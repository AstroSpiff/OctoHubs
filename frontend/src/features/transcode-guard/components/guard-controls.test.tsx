import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { GuardControls } from "@/features/transcode-guard/components/guard-controls";

describe("GuardControls", () => {
  it("keeps monitor actions mutually exclusive and reports the relevant failure nearby", () => {
    const markup = renderToStaticMarkup(
      <GuardControls
        running
        stateReady
        checking={false}
        changingState
        refreshing={false}
        error={new Error("Il monitor non puo' essere aggiornato.")}
        onCheck={() => undefined}
        onStateChange={() => undefined}
        onRefresh={() => undefined}
      />,
    );

    expect(markup).toMatch(/aria-label="Aggiorna stato"[^>]*disabled/);
    expect(markup).toMatch(/Verifica ora<\/button>/);
    expect(markup).toMatch(/<button[^>]*disabled[^>]*>[^<]*.*?Verifica ora<\/button>/);
    expect(markup).toMatch(/<input[^>]*type="checkbox"[^>]*disabled[^>]*checked/);
    expect(markup).toContain('role="alert"');
    expect(markup).toContain("Il monitor non puo&#x27; essere aggiornato.");
  });

  it.each([
    ["initial loading", undefined],
    ["initial error or stale snapshot", true],
  ])("keeps the state toggle disabled without authoritative state: %s", (_label, running) => {
    const markup = renderToStaticMarkup(
      <GuardControls
        running={running}
        stateReady={false}
        checking={false}
        changingState={false}
        refreshing={false}
        onCheck={() => undefined}
        onStateChange={() => undefined}
        onRefresh={() => undefined}
      />,
    );

    expect(markup).toMatch(/<input[^>]*type="checkbox"[^>]*disabled/);
  });

  it("keeps a resolved state actionable during a normal background refresh", () => {
    const markup = renderToStaticMarkup(
      <GuardControls
        running={false}
        stateReady
        checking={false}
        changingState={false}
        refreshing
        onCheck={() => undefined}
        onStateChange={() => undefined}
        onRefresh={() => undefined}
      />,
    );

    expect(markup).toMatch(/<input[^>]*type="checkbox"/);
    expect(markup).not.toMatch(/<input[^>]*type="checkbox"[^>]*disabled/);
  });
});
