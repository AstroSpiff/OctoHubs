import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { LatestReleaseCard } from "@/features/emby-latest/components/latest-release-card";

describe("LatestReleaseCard", () => {
  it("uses the configured server icon presentation in the server badge", () => {
    const markup = renderToStaticMarkup(
      <LatestReleaseCard
        item={{
          title: "Titolo di prova",
          server_name: "Purple",
          server_icon: "fa-film",
          server_icon_style: "regular",
          server_icon_color: "#8B5CF6",
        }}
      />,
    );

    expect(markup).toContain('data-prefix="fas"');
    expect(markup).toContain('color="#8B5CF6"');
    expect(markup).not.toContain("style=");
  });

  it("does not present internal existing state as an update", () => {
    const markup = renderToStaticMarkup(
      <LatestReleaseCard
        item={{
          title: "Movie One",
          update_type: "existing",
          update_label: "Aggiornamento",
          changes: [
            {
              kind: "existing",
              quality: "1080p",
              added_at: "2026-09-08T12:26:03+00:00",
            },
          ],
        }}
      />,
    );

    expect(markup).not.toContain("Aggiornamento");
    expect(markup).not.toContain("1080p");
  });

  it("keeps genuine new-version details visible", () => {
    const markup = renderToStaticMarkup(
      <LatestReleaseCard
        item={{
          title: "Movie One",
          update_label: "Nuova versione",
          changes: [
            {
              kind: "new_version",
              quality: "2160p",
              added_at: "2026-09-12T10:00:00+00:00",
            },
          ],
        }}
      />,
    );

    expect(markup).toContain("Nuova versione");
    expect(markup).toContain("Dettagli");
  });
});
