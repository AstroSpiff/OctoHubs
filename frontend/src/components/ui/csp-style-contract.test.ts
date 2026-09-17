// @vitest-environment jsdom

import { readdirSync, readFileSync } from "node:fs";
import { join } from "node:path";
import ts from "typescript";
import { act, createElement } from "react";
import { createRoot } from "react-dom/client";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { Server } from "@/components/ui/icons";

const sourceRoot = join(process.cwd(), "src");

function applicationSources(directory: string): string[] {
  return readdirSync(directory, { withFileTypes: true }).flatMap((entry) => {
    const path = join(directory, entry.name);
    if (entry.isDirectory()) return applicationSources(path);
    if (!/\.(?:ts|tsx)$/.test(entry.name) || entry.name.includes(".test.")) return [];
    return [path];
  });
}

function containsInlineStyleMutation(path: string): boolean {
  const source = readFileSync(path, "utf8");
  const sourceFile = ts.createSourceFile(
    path,
    source,
    ts.ScriptTarget.Latest,
    true,
    path.endsWith(".tsx") ? ts.ScriptKind.TSX : ts.ScriptKind.TS,
  );
  let violation = false;
  function visit(node: ts.Node) {
    if (
      (ts.isJsxAttribute(node) && node.name.getText(sourceFile) === "style")
      || (ts.isPropertyAccessExpression(node) && node.name.text === "style")
      || (
        ts.isCallExpression(node)
        && ts.isPropertyAccessExpression(node.expression)
        && node.expression.name.text === "setAttribute"
        && ts.isStringLiteral(node.arguments[0])
        && node.arguments[0].text.toLowerCase() === "style"
      )
    ) {
      violation = true;
      return;
    }
    ts.forEachChild(node, visit);
  }
  visit(sourceFile);
  return violation;
}

describe("strict CSP style contract", () => {
  it("keeps application rendering free from inline style mutations", () => {
    const violations = applicationSources(sourceRoot).flatMap((path) => {
      return containsInlineStyleMutation(path)
        ? [path.replace(`${sourceRoot}/`, "")]
        : [];
    });

    expect(violations).toEqual([]);
  });

  it("loads Font Awesome CSS statically and disables runtime injection", () => {
    const icons = readFileSync(join(sourceRoot, "components/ui/icons.tsx"), "utf8");

    expect(icons).toContain('@fortawesome/fontawesome-svg-core/styles.css');
    expect(icons).toMatch(/config\.autoAddCss\s*=\s*false/);
    expect(
      renderToStaticMarkup(createElement(Server, { color: "#174a73", size: 18 })),
    ).not.toContain("style=");
  });

  it("does not inject a style element when an icon mounts in the browser", () => {
    const container = document.createElement("div");
    document.body.append(container);
    const root = createRoot(container);
    const stylesBefore = document.head.querySelectorAll("style").length;

    act(() => root.render(createElement(Server, { size: 18 })));

    expect(document.head.querySelectorAll("style")).toHaveLength(stylesBefore);
    act(() => root.unmount());
    container.remove();
  });
});
