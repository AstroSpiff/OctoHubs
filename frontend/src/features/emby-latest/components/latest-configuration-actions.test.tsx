import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { LatestDataVerify } from "@/features/emby-latest/components/latest-data-verify";
import { LatestMaintenance } from "@/features/emby-latest/components/latest-maintenance";
import { LatestPresetManager } from "@/features/emby-latest/components/latest-preset-manager";

describe("Latest configuration actions", () => {
  it("holds all maintenance actions while one persistent cleanup is running", () => {
    const markup = renderToStaticMarkup(
      <LatestMaintenance
        resetting
        clearing={false}
        clearingScans={false}
        onReset={() => undefined}
        onClearState={() => undefined}
        onClearScans={() => undefined}
      />,
    );

    expect(markup).toContain("Manutenzione pubblicazioni in corso...");
    expect(markup.match(/<button[^>]*\sdisabled(?:=|\s|>)/g)).toHaveLength(3);
  });

  it("locks preset changes and keeps their failure in the preset card", () => {
    const markup = renderToStaticMarkup(
      <LatestPresetManager
        presets={[{ id: "main", name: "Principale", template: "{{ title }}" }]}
        saving
        onSave={async () => undefined}
        onRemove={() => undefined}
        onTemplateChange={() => undefined}
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
      />,
    );

    expect(markup.match(/<select[^>]*\sdisabled(?:=|\s|>)/g)).toHaveLength(3);
  });
});
