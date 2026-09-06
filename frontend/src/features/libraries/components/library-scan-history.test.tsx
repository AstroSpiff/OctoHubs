import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { LibraryScanHistory } from "@/features/libraries/components/library-scan-history";

const baseProps = {
  loading: false,
  resetting: false,
  onRefresh: () => undefined,
  onReset: () => undefined,
  onDelete: () => undefined,
};

describe("LibraryScanHistory", () => {
  it("does not render a false empty history or enable reset before a snapshot", () => {
    const markup = renderToStaticMarkup(
      <LibraryScanHistory jobs={[]} hasData={false} {...baseProps} />,
    );

    expect(markup).toContain("Caricamento cronologia scansioni");
    expect(markup).not.toContain("Nessuna scansione registrata");
    expect(markup).toMatch(
      /aria-label="Azzera stato scansioni e metadata"[^>]*disabled/,
    );
  });

  it("renders success-empty only after the history snapshot resolves", () => {
    const markup = renderToStaticMarkup(
      <LibraryScanHistory jobs={[]} hasData {...baseProps} />,
    );

    expect(markup).toContain("Nessuna scansione registrata");
    expect(markup).not.toContain("Caricamento cronologia scansioni");
  });

  it("renders a retryable error without an empty claim when no snapshot exists", () => {
    const markup = renderToStaticMarkup(
      <LibraryScanHistory
        jobs={[]}
        hasData={false}
        error={new Error("Cronologia non disponibile")}
        {...baseProps}
      />,
    );

    expect(markup).toContain("Cronologia non disponibile");
    expect(markup).toContain("Riprova");
    expect(markup).not.toContain("Nessuna scansione registrata");
  });
});
