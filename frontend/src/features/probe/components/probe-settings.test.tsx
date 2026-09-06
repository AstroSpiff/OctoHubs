import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { ProbeSettings } from "@/features/probe/components/probe-settings";


describe("ProbeSettings loading contract", () => {
  it("does not expose editable defaults before the server configuration loads", () => {
    const markup = renderToStaticMarkup(
      <ProbeSettings
        scope="libraries"
        config={undefined}
        disabled
        loading
        saving={false}
        saved={false}
        onSave={async (config) => config}
      />,
    );

    expect(markup).toContain("Caricamento configurazione Probe");
    expect(markup).not.toContain("File da analizzare");
    expect(markup).not.toContain("Salva");
  });

  it("shows a read failure without constructing a resettable draft", () => {
    const markup = renderToStaticMarkup(
      <ProbeSettings
        scope="recent"
        config={undefined}
        disabled
        loadError="Servizio non disponibile"
        saving={false}
        saved={false}
        onSave={async (config) => config}
      />,
    );

    expect(markup).toContain("Impossibile caricare la configurazione Probe");
    expect(markup).not.toContain("Ripristina");
  });
});
