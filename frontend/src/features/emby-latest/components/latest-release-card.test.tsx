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
    expect(markup).toContain("color:#8B5CF6");
  });
});
