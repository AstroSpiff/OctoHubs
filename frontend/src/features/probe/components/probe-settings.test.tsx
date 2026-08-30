import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { ProbeSettings } from "@/features/probe/components/probe-settings";
import { probeConfigDefaults } from "@/features/probe/presentation";

describe("ProbeSettings", () => {
  it("shows shared media settings for libraries", () => {
    const markup = renderToStaticMarkup(
      <ProbeSettings
        scope="libraries"
        serverName="Green"
        config={probeConfigDefaults}
        disabled={false}
        saving={false}
        saved
        onSave={async (config) => config}
      />,
    );

    expect(markup).toContain("Solo file STRM");
    expect(markup).toContain("File video senza MediaInfo");
    expect(markup).toContain("Configurazione Probe salvata.");
    expect(markup).not.toContain("Finestra scorrevole");
  });

  it("adds recent-only settings for latest items", () => {
    const markup = renderToStaticMarkup(
      <ProbeSettings
        scope="recent"
        config={probeConfigDefaults}
        disabled={false}
        saving={false}
        saved={false}
        onSave={async (config) => config}
      />,
    );

    expect(markup).toContain("Finestra scorrevole");
    expect(markup).toContain("Intervallo di ricerca");
  });

  it("allows choosing a configuration target while recent operations use all servers", () => {
    const markup = renderToStaticMarkup(
      <ProbeSettings
        scope="recent"
        serverName="Green"
        config={probeConfigDefaults}
        disabled={false}
        saving={false}
        saved={false}
        configServers={[{ id: "green", name: "Green" }, { id: "purple", name: "Purple" }]}
        configServerId="green"
        onConfigServerChange={() => true}
        onSave={async (config) => config}
      />,
    );

    expect(markup).toContain("Server da configurare");
    expect(markup).toContain("Green");
    expect(markup).toContain("Purple");
  });
});
