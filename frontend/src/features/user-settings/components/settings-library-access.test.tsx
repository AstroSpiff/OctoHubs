import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { SettingsLibraryAccess } from "@/features/user-settings/components/settings-library-access";
import { normalizeUserSettings } from "@/features/user-settings/settings-model";

describe("SettingsLibraryAccess", () => {
  it("keeps the library inventory visible in all-libraries mode and identifies grouped entries", () => {
    const markup = renderToStaticMarkup(
      <SettingsLibraryAccess
        settings={normalizeUserSettings({ libraries: { mode: "all" } })}
        items={[{
          id: "movies",
          name: "Film",
          collection_type: "movies",
          group_key: "movies:main",
        }]}
        disabled={false}
        onChange={() => undefined}
      />,
    );

    expect(markup).toContain("Film (movies)");
    expect(markup).toContain("Gruppo");
    expect(markup).toContain("is-readonly");
    expect(markup).toContain('type="checkbox" disabled="" checked=""');
  });
});
