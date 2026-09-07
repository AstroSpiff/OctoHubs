// @vitest-environment jsdom

import { readdirSync, readFileSync } from "node:fs";
import { join, relative } from "node:path";
import ts from "typescript";
import { describe, expect, it, vi } from "vitest";

import {
  downloadBrowserFile,
  navigateBrowser,
  writeBrowserClipboard,
} from "@/lib/browser-download";

const ownerBoundBrowserWorkflows = [
  "../features/account-management/components/api-token-audit-panel.tsx",
  "../components/account-menu.tsx",
  "../features/research/components/search-result-batch-actions.tsx",
  "../features/research/components/search-result-actions.tsx",
] as const;

describe("browser side-effect owner contract", () => {
  it.each(ownerBoundBrowserWorkflows)("fences %s to its initiating owner", (relativePath) => {
    const source = readFileSync(join(process.cwd(), "src/lib", relativePath), "utf8");

    expect(source).toContain("useOwnerBoundBrowserAction");
    expect(source).toContain("action.signal");
    expect(source).not.toMatch(/navigator\.clipboard|window\.location\.assign|URL\.createObjectURL|document\.createElement\(["']a["']\)/);
  });

  it("routes token clipboard writes through an owner-bound canonical helper", () => {
    const source = readFileSync(
      join(process.cwd(), "src/features/account-management/components/api-token-panel.tsx"),
      "utf8",
    );

    expect(source).toContain("useOwnerBoundBrowserAction");
    expect(source).toContain("writeBrowserClipboard(secret, action)");
    expect(source).not.toContain("navigator.clipboard");
  });

  it("keeps async browser primitives behind the canonical guarded module repository-wide", () => {
    const sourceRoot = join(process.cwd(), "src");
    const violations: string[] = [];
    for (const filename of applicationTypeScriptFiles(sourceRoot)) {
      if (filename.endsWith("/lib/browser-download.ts")) continue;
      const source = ts.createSourceFile(
        filename,
        readFileSync(filename, "utf8"),
        ts.ScriptTarget.Latest,
        true,
        filename.endsWith(".tsx") ? ts.ScriptKind.TSX : ts.ScriptKind.TS,
      );
      visit(source, (node) => {
        if (!ts.isCallExpression(node) || !sensitiveBrowserPrimitive(node)) return;
        if (!belongsToAsyncWorkflow(node)) return;
        const { line } = source.getLineAndCharacterOfPosition(node.getStart(source));
        violations.push(`${relative(sourceRoot, filename)}:${line + 1} ${node.expression.getText(source)}`);
      });
    }

    expect(violations, violations.join("\n")).toEqual([]);
  });

  it("keeps browser primitives behind a mandatory current-owner guard", () => {
    const relativePath = "./browser-download.ts";
    const source = readFileSync(join(process.cwd(), "src/lib", relativePath), "utf8");

    expect(source.match(/guard\.assertCurrent\(\)/g)?.length).toBeGreaterThanOrEqual(4);
    expect(source).toContain("navigator.clipboard.writeText");
    expect(source).toContain("window.location.assign");
    expect(source).toContain("URL.createObjectURL");
  });

  it("performs no browser effect when the owner guard is stale", async () => {
    const stale = { assertCurrent: vi.fn(() => { throw new Error("stale owner"); }) };
    const originalCreateObjectUrl = URL.createObjectURL;
    const createObjectUrl = vi.fn(() => "blob:test");
    Object.defineProperty(URL, "createObjectURL", { configurable: true, value: createObjectUrl });
    const clipboard = { writeText: vi.fn().mockResolvedValue(undefined) };
    Object.defineProperty(navigator, "clipboard", { configurable: true, value: clipboard });

    try {
      expect(() => downloadBrowserFile(new Blob(["audit"]), "audit.json", stale)).toThrow("stale owner");
      await expect(writeBrowserClipboard("magnet", stale)).rejects.toThrow("stale owner");
      expect(() => navigateBrowser("magnet:?xt=test", stale)).toThrow("stale owner");

      expect(createObjectUrl).not.toHaveBeenCalled();
      expect(clipboard.writeText).not.toHaveBeenCalled();
    } finally {
      Object.defineProperty(URL, "createObjectURL", {
        configurable: true,
        value: originalCreateObjectUrl,
      });
    }
  });
});

function applicationTypeScriptFiles(directory: string): string[] {
  return readdirSync(directory, { withFileTypes: true }).flatMap((entry) => {
    const path = join(directory, entry.name);
    if (entry.isDirectory()) return applicationTypeScriptFiles(path);
    return /\.tsx?$/.test(entry.name) && !entry.name.includes(".test.") ? [path] : [];
  });
}

function visit(node: ts.Node, callback: (node: ts.Node) => void) {
  callback(node);
  ts.forEachChild(node, (child) => visit(child, callback));
}

function belongsToAsyncWorkflow(node: ts.Node) {
  let current = node.parent;
  while (current) {
    if (
      ts.isFunctionLike(current)
      && (isAsync(current) || isPromiseContinuation(current))
    ) return true;
    current = current.parent;
  }
  return false;
}

function isAsync(node: ts.SignatureDeclaration) {
  return Boolean(
    ts.canHaveModifiers(node)
    && ts.getModifiers(node)?.some((modifier) => modifier.kind === ts.SyntaxKind.AsyncKeyword),
  );
}

function isPromiseContinuation(node: ts.SignatureDeclaration) {
  const call = node.parent;
  if (!ts.isCallExpression(call) || !call.arguments.includes(node as ts.Expression)) return false;
  return ts.isPropertyAccessExpression(call.expression)
    && ["then", "catch", "finally"].includes(call.expression.name.text);
}

function sensitiveBrowserPrimitive(node: ts.CallExpression) {
  const expression = node.expression.getText();
  if ([
    "navigator.clipboard.writeText",
    "window.location.assign",
    "URL.createObjectURL",
  ].includes(expression)) return true;
  return expression === "document.createElement"
    && ts.isStringLiteral(node.arguments[0])
    && node.arguments[0].text.toLowerCase() === "a";
}
