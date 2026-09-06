import { readdirSync, readFileSync } from "node:fs";
import { join } from "node:path";
import { fileURLToPath } from "node:url";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";

import { QueryStateBoundary } from "@/components/ui/query-state-boundary";
import { queryStateFallbackViolations } from "@/components/ui/query-state-source-gate";

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

  it("gates Latest configuration and snapshot independently", () => {
    const source = readFileSync(
      new URL("../../pages/latest-page.tsx", import.meta.url),
      "utf8",
    );

    expect(source).toContain("hasData={Boolean(configuration)}");
    expect(source).toContain("hasData={Boolean(snapshot)}");
    expect(source.match(/<QueryStateBoundary/g)).toHaveLength(2);
  });

  it("guards query-backed empty claims across the source tree", () => {
    const sourceRoot = fileURLToPath(new URL("../../", import.meta.url));
    const sourceFiles = collectSourceFiles(sourceRoot);
    const violations = sourceFiles.flatMap((sourcePath) =>
      queryStateFallbackViolations(
        readFileSync(sourcePath, "utf8"),
        sourcePath.slice(sourceRoot.length),
      ),
    );

    expect(violations).toEqual([]);
  });

  it("does not let an unrelated boundary for the same receiver make an empty claim pass", () => {
    const source = `
      const items = unresolved.data?.items || [];
      return <>
        <QueryStateBoundary hasData={Boolean(unresolved.data)}>other surface</QueryStateBoundary>
        {!items.length ? <p>Nessun elemento.</p> : null}
      </>;
    `;

    expect(queryStateFallbackViolations(source, "unsafe.tsx").length).toBeGreaterThan(0);
  });

  it("rejects query-state labels when the empty claim itself remains unconditional", () => {
    const source = `
      const items = query.data?.items || [];
      return <>
        {query.isLoading ? <p>Loading</p> : null}
        {query.error ? <p>Error</p> : null}
        {!items.length ? <p>Nessun elemento.</p> : null}
      </>;
    `;

    expect(queryStateFallbackViolations(source, "unsafe.tsx").length).toBeGreaterThan(0);
  });

  it("follows snapshot and collection aliases through ternary empty branches", () => {
    const source = `
      const snapshot = query.data;
      const records = snapshot?.items || [];
      const visibleRecords = records;
      return visibleRecords.length
        ? <List items={visibleRecords} />
        : <p>Nessun elemento.</p>;
    `;

    expect(queryStateFallbackViolations(source, "unsafe.tsx").length).toBeGreaterThan(0);
  });

  it("rejects an unguarded zero metric derived from a query snapshot", () => {
    const source = `
      function Metrics() {
        const count = query.data?.count ?? 0;
        return <Metric value={count} />;
      }
    `;
    const guarded = `
      function Metrics() {
        const count = query.data?.count ?? 0;
        return <QueryStateBoundary hasData={Boolean(query.data)}>
          <Metric value={count} />
        </QueryStateBoundary>;
      }
    `;

    expect(queryStateFallbackViolations(source, "unsafe.tsx")).toHaveLength(1);
    expect(queryStateFallbackViolations(guarded, "safe.tsx")).toEqual([]);
  });

  it("rejects ternary zero and collection fallbacks derived from a query snapshot", () => {
    const source = `
      function Surface() {
        const count = query.data ? query.data.count : 0;
        const items = query.data ? query.data.items : [];
        return <><Metric value={count} /><List items={items} /></>;
      }
    `;

    expect(queryStateFallbackViolations(source, "unsafe.tsx")).toHaveLength(2);
  });

  it("accepts a fallback prop paired with hasData for the same snapshot only", () => {
    const safe = `
      function Surface() {
        return <List items={query.data?.items || []} hasData={Boolean(query.data)} />;
      }
    `;
    const unrelated = `
      function Surface() {
        return <List items={query.data?.items || []} hasData={Boolean(other.data)} />;
      }
    `;

    expect(queryStateFallbackViolations(safe, "safe.tsx")).toEqual([]);
    expect(queryStateFallbackViolations(unrelated, "unsafe.tsx")).toHaveLength(1);
  });

  it("accepts an early snapshot guard and an enclosing boundary", () => {
    const earlyReturn = `
      function Surface() {
        const items = query.data?.items || [];
        if (!query.data) return <p>Loading</p>;
        return !items.length ? <p>Nessun elemento.</p> : <List items={items} />;
      }
    `;
    const boundary = `
      function Surface() {
        const items = query.data?.items || [];
        return <QueryStateBoundary hasData={Boolean(query.data)}>
          {!items.length ? <p>Nessun elemento.</p> : <List items={items} />}
        </QueryStateBoundary>;
      }
    `;

    expect(queryStateFallbackViolations(earlyReturn, "safe.tsx")).toEqual([]);
    expect(queryStateFallbackViolations(boundary, "safe.tsx")).toEqual([]);
  });

  it("rejects snapshot boolean decisions that directly drive mutations", () => {
    const direct = `
      function Controls() {
        const snapshot = status.data;
        return <button onClick={() => state.mutate(snapshot?.running ? "stop" : "start")}>Toggle</button>;
      }
    `;
    const alias = `
      function Controls() {
        const running = Boolean(status.data?.running);
        return <button onClick={() => state.mutate(running ? "stop" : "start")}>Toggle</button>;
      }
    `;
    const booleanArgument = `
      function Controls() {
        return <button onClick={() => state.mutate(Boolean(status.data?.running))}>Save</button>;
      }
    `;

    expect(queryStateFallbackViolations(direct, "unsafe.tsx")).toHaveLength(1);
    expect(queryStateFallbackViolations(alias, "unsafe.tsx")).toHaveLength(1);
    expect(queryStateFallbackViolations(booleanArgument, "unsafe.tsx")).toHaveLength(1);
  });

  it("requires the mutation decision's own snapshot guard", () => {
    const guarded = `
      function Controls() {
        const snapshot = status.data;
        function toggle() {
          if (!snapshot) return;
          state.mutate(snapshot.running ? "stop" : "start");
        }
        return <button onClick={toggle}>Toggle</button>;
      }
    `;
    const unrelated = `
      function Controls() {
        const snapshot = status.data;
        function toggle() {
          if (!other.data) return;
          state.mutate(snapshot?.running ? "stop" : "start");
        }
        return <button onClick={toggle}>Toggle</button>;
      }
    `;

    expect(queryStateFallbackViolations(guarded, "safe.tsx")).toEqual([]);
    expect(queryStateFallbackViolations(unrelated, "unsafe.tsx")).toHaveLength(1);
  });
});

function collectSourceFiles(directory: string): string[] {
  return readdirSync(directory, { withFileTypes: true }).flatMap((entry) => {
    const path = join(directory, entry.name);
    if (entry.isDirectory()) return collectSourceFiles(path);
    return entry.name.endsWith(".tsx") && !entry.name.includes(".test.")
      ? [path]
      : [];
  });
}
