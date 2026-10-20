import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { LatestDataVerify } from "@/features/emby-latest/components/latest-data-verify";
import {
  LatestNotificationsMaintenance,
  LatestPublicationsMaintenance,
} from "@/features/emby-latest/components/latest-maintenance";
import { LatestPresetManager } from "@/features/emby-latest/components/latest-preset-manager";
import { LatestRuleManager } from "@/features/emby-latest/components/latest-rule-manager";

describe("Latest configuration actions", () => {
  it("keeps each maintenance action in its own domain", () => {
    const publications = renderToStaticMarkup(
      <LatestPublicationsMaintenance resetting onReset={() => undefined} />,
    );
    const notifications = renderToStaticMarkup(
      <LatestNotificationsMaintenance
        clearing
        onClearState={() => undefined}
      />,
    );

    expect(publications).toContain("Ricostruisci pubblicazioni");
    expect(publications).not.toContain("Reimposta notifiche inviate");
    expect(notifications).toContain("Reimposta notifiche inviate");
    expect(notifications).not.toContain("scan/metadata");
    expect(publications.match(/<button[^>]*\sdisabled(?:=|\s|>)/g)).toHaveLength(1);
    expect(notifications.match(/<button[^>]*\sdisabled(?:=|\s|>)/g)).toHaveLength(1);
  });

  it("locks preset changes and keeps their failure in the preset card", () => {
    const markup = renderToStaticMarkup(
      <LatestPresetManager
        presets={[{ id: "main", name: "Principale", template: "{{ title }}" }]}
        saving
        selectedPresetId="main"
        onSave={async () => undefined}
        onRemove={() => undefined}
        onSelectPreset={() => undefined}
        onDraftChange={() => undefined}
        error="Impossibile salvare il preset."
      />,
    );

    expect(markup).toContain("Salvataggio configurazione in corso...");
    expect(markup).toContain('role="alert"');
    expect(markup).toContain("Impossibile salvare il preset.");
    expect(markup.match(/<button[^>]*\sdisabled(?:=|\s|>)/g)?.length).toBeGreaterThanOrEqual(4);
  });

  it("does not allow switching the content while enrichment is in progress", () => {
    const markup = renderToStaticMarkup(
      <LatestDataVerify
        open
        servers={[{ id: "green", name: "Green" }]}
        movies={[{ item_id: "movie-1", server_id: "green", title: "Film" }]}
        series={[]}
        enriching
        onClose={() => undefined}
        onEnrich={async (item) => item}
        onResetError={() => undefined}
      />,
    );

    expect(markup.match(/<select[^>]*\sdisabled(?:=|\s|>)/g)).toHaveLength(3);
  });

  it("keeps the new notification action concise without losing its accessible name", () => {
    const markup = renderToStaticMarkup(
      <LatestRuleManager
        rules={[]}
        servers={[]}
        presets={[]}
        telegramPresets={[]}
        saving={false}
        onSave={async () => undefined}
        onToggle={() => undefined}
        onRemove={() => undefined}
      />,
    );

    expect(markup).toContain('aria-label="Nuova regola di notifica"');
    expect(markup).toMatch(/<button[^>]*>.*Nuova<\/button>/);
    expect(markup).not.toContain("Nuova regola</button>");
  });
});
