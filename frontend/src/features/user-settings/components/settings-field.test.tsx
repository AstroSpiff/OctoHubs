import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { SettingsFieldControl } from "@/features/user-settings/components/settings-field";

describe("SettingsFieldControl", () => {
  it("keeps integer constraints from the settings schema in the editor", () => {
    const markup = renderToStaticMarkup(
      <SettingsFieldControl
        field={{
          key: "RemoteClientBitrateLimit",
          label: "Limite bitrate",
          type: "int",
          min: 0,
          max: 1000000,
        }}
        scope="policy"
        value={500000}
        disabled={false}
        onChange={() => undefined}
      />,
    );

    expect(markup).toContain('type="number"');
    expect(markup).toContain('min="0"');
    expect(markup).toContain('max="1000000"');
    expect(markup).toContain('step="1"');
  });

  it("renders library multi fields as the legacy selectable library list", () => {
    const markup = renderToStaticMarkup(
      <SettingsFieldControl
        field={{
          key: "LatestItemsExcludes",
          label: "Escludi da Media recenti",
          type: "library_multi",
        }}
        scope="config"
        value={["legacy-movies", "removed-library"]}
        disabled={false}
        libraryItems={[
          {
            id: "movies",
            name: "Film",
            collection_type: "movie",
            alt_ids: ["legacy-movies"],
            group_key: "movie:main",
          },
        ]}
        onChange={() => undefined}
      />,
    );

    expect(markup).toContain("Film (movie)");
    expect(markup).toContain("Gruppo");
    expect(markup).toContain("ID: removed-library");
  });

  it("honors password and length metadata from the settings schema", () => {
    const markup = renderToStaticMarkup(
      <SettingsFieldControl
        field={{
          key: "ProfilePin",
          label: "PIN del profilo",
          type: "password",
          max_length: 32,
        }}
        scope="config"
        value="1234"
        disabled={false}
        onChange={() => undefined}
      />,
    );

    expect(markup).toContain('type="password"');
    expect(markup).toContain('maxLength="32"');
  });
});
