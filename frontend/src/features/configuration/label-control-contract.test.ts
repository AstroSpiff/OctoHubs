import { readdirSync, readFileSync } from "node:fs";
import { join, relative } from "node:path";
import { fileURLToPath } from "node:url";
import ts from "typescript";
import { describe, expect, it } from "vitest";

const sourceRoot = fileURLToPath(new URL("../../", import.meta.url));
const interactiveElements = new Set(["input", "select", "textarea", "button", "a"]);
const interactiveComponentName = /(Button|Control|Input|Select|Checkbox|Radio|Switch|Toggle|Picker)$/;

describe("repository label semantics", () => {
  it("never nests multiple controls or another label inside a label", () => {
    const violations: string[] = [];
    for (const filename of applicationTsxFiles(sourceRoot)) {
      const source = ts.createSourceFile(
        filename,
        readFileSync(filename, "utf8"),
        ts.ScriptTarget.Latest,
        true,
        ts.ScriptKind.TSX,
      );
      visit(source, (node) => {
        if (!ts.isJsxElement(node) || tagName(node.openingElement) !== "label") return;
        const controls: string[] = [];
        visit(node, (descendant) => {
          if (descendant === node) return;
          if (ts.isJsxElement(descendant) && tagName(descendant.openingElement) === "label") {
            controls.push("nested label");
            return;
          }
          if (!ts.isJsxElement(descendant) && !ts.isJsxSelfClosingElement(descendant)) return;
          const opening = ts.isJsxElement(descendant)
            ? descendant.openingElement
            : descendant;
          const name = tagName(opening);
          if (
            interactiveElements.has(name)
            || (
              isComponentName(name)
              && (interactiveComponentName.test(name) || hasInteractionProp(opening))
            )
          ) controls.push(name);
        });
        if (controls.length > 1 || controls.includes("nested label")) {
          const { line } = source.getLineAndCharacterOfPosition(node.getStart(source));
          violations.push(
            `${relative(sourceRoot, filename)}:${line + 1} contains ${controls.join(", ")}`,
          );
        }
      });
    }

    expect(violations, violations.join("\n")).toEqual([]);
  });
});

function applicationTsxFiles(directory: string): string[] {
  return readdirSync(directory, { withFileTypes: true }).flatMap((entry) => {
    const path = join(directory, entry.name);
    if (entry.isDirectory()) return applicationTsxFiles(path);
    return entry.name.endsWith(".tsx") && !entry.name.includes(".test.") ? [path] : [];
  });
}

function visit(node: ts.Node, callback: (node: ts.Node) => void) {
  callback(node);
  ts.forEachChild(node, (child) => visit(child, callback));
}

function tagName(node: ts.JsxOpeningLikeElement) {
  return node.tagName.getText();
}

function isComponentName(name: string) {
  return /^[A-Z]/.test(name);
}

function hasInteractionProp(node: ts.JsxOpeningLikeElement) {
  return node.attributes.properties.some((attribute) => {
    if (!ts.isJsxAttribute(attribute)) return false;
    const name = attribute.name.getText();
    return /^on[A-Z]/.test(name) || name === "href";
  });
}
