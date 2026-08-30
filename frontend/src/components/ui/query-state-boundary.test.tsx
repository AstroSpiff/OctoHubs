import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";

import { QueryStateBoundary } from "@/components/ui/query-state-boundary";

describe("QueryStateBoundary", () => {
  it("shows an error with retry instead of an endless loading state", () => {
    const markup = renderToStaticMarkup(
      <QueryStateBoundary
        error={new Error("Servizio non disponibile")}
        hasData={false}
        loadingLabel="Caricamento dati..."
        onRetry={vi.fn()}
      >
        <div>Contenuto</div>
      </QueryStateBoundary>,
    );

    expect(markup).toContain("Servizio non disponibile");
    expect(markup).toContain("Riprova");
    expect(markup).not.toContain("Caricamento dati");
    expect(markup).not.toContain("Contenuto");
  });

  it("uses the loading state only before data or an error exist", () => {
    const markup = renderToStaticMarkup(
      <QueryStateBoundary
        hasData={false}
        loadingLabel="Caricamento dati..."
        onRetry={vi.fn()}
      >
        <div>Contenuto</div>
      </QueryStateBoundary>,
    );

    expect(markup).toContain("Caricamento dati...");
    expect(markup).not.toContain("Riprova");
  });

  it("keeps stale data visible beside a refresh error", () => {
    const markup = renderToStaticMarkup(
      <QueryStateBoundary
        error={new Error("Refresh non riuscito")}
        hasData
        loadingLabel="Caricamento dati..."
        onRetry={vi.fn()}
      >
        <div>Contenuto disponibile</div>
      </QueryStateBoundary>,
    );

    expect(markup).toContain("Refresh non riuscito");
    expect(markup).toContain("Contenuto disponibile");
  });
});
