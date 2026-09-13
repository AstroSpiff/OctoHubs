import { readFileSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

const featureCss = readFileSync(join(__dirname, "emby-latest.css"), "utf8");
const cardsCss = readFileSync(
  join(__dirname, "components/latest-release-card.css"),
  "utf8",
);
const configurationCss = readFileSync(
  join(__dirname, "components/latest-notification-configuration.css"),
  "utf8",
);

describe("Latest responsive layout", () => {
  it("derives content breakpoints from the workspace instead of the viewport", () => {
    expect(featureCss).toContain("container: latest-workspace / inline-size");
    expect(cardsCss).toContain("@container latest-workspace (max-width: 680px)");
    expect(configurationCss).toContain(
      "@container latest-workspace (max-width: 1120px)",
    );
    expect(configurationCss).toContain(
      "@container latest-workspace (max-width: 760px)",
    );
    expect(configurationCss).not.toContain("@media (max-width: 1120px)");
  });

  it("keeps two release columns near 1120px and stacks only when truly narrow", () => {
    expect(cardsCss).toContain(
      "grid-template-columns: repeat(2, minmax(0, 1fr))",
    );
    expect(cardsCss).toMatch(
      /@container latest-workspace \(max-width: 680px\)\s*\{\s*\.latest-release-grid\s*\{\s*grid-template-columns:\s*1fr;/,
    );
    expect(featureCss).toMatch(
      /@container latest-workspace \(max-width: 900px\)[\s\S]*?\.latest-display-limit\s*\{[\s\S]*?justify-content:\s*flex-start;/,
    );
  });
});
