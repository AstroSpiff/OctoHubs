import { readFileSync } from "node:fs";
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
    expect(markup).toContain('role="status"');
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

  it.each([
    ["Users", "../../pages/users-page.tsx", "users.dashboard.data"],
    ["Libraries", "../../pages/libraries-page.tsx", "libraries.groups.data"],
    ["Collections", "../../pages/collections-page.tsx", "collections.collections.data"],
  ])("gates the %s empty state on resolved query data", (_name, sourcePath, dataExpression) => {
    const source = readFileSync(new URL(sourcePath, import.meta.url), "utf8");

    expect(source).toContain("<QueryStateBoundary");
    expect(source).toContain(`hasData={Boolean(${dataExpression})}`);
  });
});
