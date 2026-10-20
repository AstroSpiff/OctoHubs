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
const latestPage = readFileSync(
  join(__dirname, "../../pages/latest-page.tsx"),
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
      /@container latest-workspace \(max-width: 900px\)[\s\S]*?\.latest-context-toolbar--publications \.latest-context-commands\s*\{[\s\S]*?flex-basis:\s*100%;/,
    );
  });

  it("moves the new-rule action only in the narrow mobile layout", () => {
    expect(configurationCss).toMatch(
      /@container latest-workspace \(max-width: 480px\)[\s\S]*?\.latest-rule-manager > header\s*\{[\s\S]*?flex-direction:\s*column;/,
    );
    expect(configurationCss).toMatch(
      /@container latest-workspace \(max-width: 480px\)[\s\S]*?\.latest-rule-create-button\s*\{[\s\S]*?align-self:\s*flex-start;/,
    );
  });

  it("places one shared server selector below the view tabs", () => {
    const tabsIndex = latestPage.indexOf("<LatestViewTabs");
    const selectorIndex = latestPage.indexOf("<LatestServerSelector");

    expect(tabsIndex).toBeGreaterThan(-1);
    expect(selectorIndex).toBeGreaterThan(tabsIndex);
    expect(latestPage.match(/<LatestServerSelector/g)).toHaveLength(1);
    expect(latestPage).toContain("selectedServer={serverId}");
    expect(latestPage).toContain('className="latest-view-controls"');
    expect(latestPage).toContain('className="latest-view-layout"');
    expect(featureCss).toContain("--latest-related-gap: 6px");
    expect(featureCss).toContain("--latest-content-gap: 12px");
    expect(featureCss).toMatch(
      /\.latest-view-controls\s*\{[\s\S]*?gap:\s*var\(--latest-related-gap\);/,
    );
    expect(featureCss).toMatch(
      /\.latest-view-panel\s*\{[\s\S]*?gap:\s*var\(--latest-content-gap\);/,
    );
  });

  it("keeps server, contextual actions and publication metadata in one compact toolbar", () => {
    expect(latestPage).not.toContain(
      "Consulta film e serie TV rilevati sui server Emby selezionati.",
    );
    expect(latestPage).not.toContain(
      "Configura preset messaggi e regole di notifica per le pubblicazioni recenti.",
    );
    expect(latestPage).toContain("latest-context-toolbar--${activeView}");
    expect(latestPage).toContain('className="latest-context-commands"');
    expect(latestPage).toContain(
      'className="latest-publications-toolbar-meta"',
    );
    expect(featureCss).toMatch(
      /\.latest-context-toolbar\s*\{[\s\S]*?flex-wrap:\s*wrap;/,
    );
    expect(featureCss).toMatch(
      /\.latest-server-tabs\s*\{[\s\S]*?flex-wrap:\s*nowrap;[\s\S]*?overflow-x:\s*auto;/,
    );
    expect(featureCss).not.toContain(".latest-view-description");
    expect(featureCss).not.toMatch(
      /@media \(max-width: 480px\)[\s\S]*?\.latest-view-actions\s*\{[\s\S]*?grid-template-columns:/,
    );
  });
});
