import { readdirSync, readFileSync } from "node:fs";
import { dirname, extname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

const stylesDirectory = dirname(fileURLToPath(import.meta.url));
const sourceDirectory = dirname(stylesDirectory);

function cssFiles(directory: string): string[] {
  return readdirSync(directory, { withFileTypes: true }).flatMap((entry) => {
    const path = join(directory, entry.name);
    if (entry.isDirectory()) return cssFiles(path);
    return extname(entry.name) === ".css" ? [path] : [];
  });
}

function colorTokens(source: string, pattern: RegExp): Set<string> {
  return new Set(Array.from(source.matchAll(pattern), ([, token]) => token));
}

describe("color tokens", () => {
  it("defines every shared color variable used by feature styles", () => {
    const palette = readFileSync(join(stylesDirectory, "globals.css"), "utf8");
    const defined = colorTokens(palette, /(?:^|[;\s{])(--color-[a-z-]+)\s*:/gm);
    const used = new Set(cssFiles(sourceDirectory).flatMap((path) => [
      ...colorTokens(readFileSync(path, "utf8"), /var\((--color-[a-z-]+)/g),
    ]));

    expect([...used].filter((token) => !defined.has(token)).sort()).toEqual([]);
  });

  it("keeps concrete color values inside the shared palette", () => {
    const directColor = /#[0-9a-f]{3,8}\b|rgba?\(|hsla?\(/i;
    const filesWithDirectColors = cssFiles(sourceDirectory)
      .filter((path) => path !== join(stylesDirectory, "globals.css"))
      .filter((path) => directColor.test(readFileSync(path, "utf8")))
      .map((path) => path.replace(`${sourceDirectory}/`, ""));

    expect(filesWithDirectColors).toEqual([]);
  });

  it("gives every shared inline-alert severity a semantic visual treatment", () => {
    const palette = readFileSync(join(stylesDirectory, "globals.css"), "utf8");

    expect(palette).toMatch(/\.inline-alert--error\s*\{[\s\S]*?var\(--color-danger-border\)/);
    expect(palette).toMatch(/\.inline-alert--success\s*\{[\s\S]*?var\(--color-success-border\)/);
    expect(palette).toMatch(/\.inline-alert--warning\s*\{[\s\S]*?var\(--color-warning-border\)/);
    expect(palette).toMatch(/\.inline-alert--info\s*\{[\s\S]*?var\(--color-info-border\)/);
  });

  it("keeps closed native disclosures hidden when their content defines a layout", () => {
    const palette = readFileSync(join(stylesDirectory, "globals.css"), "utf8");

    expect(palette).toMatch(
      /details:not\(\[open\]\)\s*>\s*:not\(summary\)\s*\{\s*display:\s*none;/,
    );
  });

  it("defines a complete semantic palette for the dark theme", () => {
    const palette = readFileSync(join(stylesDirectory, "globals.css"), "utf8");
    const darkTheme = palette.match(/html\[data-theme="dark"\]\s*\{([\s\S]*?)\n\}/)?.[1] || "";

    for (const token of [
      "--color-canvas",
      "--color-surface",
      "--color-surface-muted",
      "--color-ink",
      "--color-ink-strong",
      "--color-muted",
      "--color-border",
      "--color-accent",
      "--color-success",
      "--color-warning",
      "--color-danger",
      "--color-info",
    ]) {
      expect(darkTheme).toMatch(new RegExp(`${token}\\s*:`));
    }
  });
});
