import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { GuardControls } from "@/features/transcode-guard/components/guard-controls";

describe("GuardControls", () => {
  it("keeps monitor actions mutually exclusive and reports the relevant failure nearby", () => {
    const markup = renderToStaticMarkup(
      <GuardControls
        running
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
});
