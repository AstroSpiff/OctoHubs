import { readdirSync, readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

const sourceRoot = join(process.cwd(), "src");

describe("interactive selection state contract", () => {
  it("gives every active native button a programmatic selected state", () => {
    const violations = sourceFiles(sourceRoot).flatMap((filename) => {
      const source = readFileSync(filename, "utf8");
      const buttons = source.match(/<button\b[\s\S]*?(?:<\/button>|\/>)/g) || [];
      return buttons
        .filter((button) => button.includes("is-active"))
        .filter((button) => !/aria-(?:pressed|selected|current)=/.test(button))
        .map(() => filename.slice(sourceRoot.length + 1));
    });

    expect(violations).toEqual([]);
  });
});

function sourceFiles(directory: string): string[] {
  return readdirSync(directory, { withFileTypes: true }).flatMap((entry) => {
    const path = join(directory, entry.name);
    if (entry.isDirectory()) return sourceFiles(path);
    return entry.isFile() && path.endsWith(".tsx") ? [path] : [];
  });
}
