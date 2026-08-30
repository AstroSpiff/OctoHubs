import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { LiveOverview } from "@/features/emby-live/components/live-overview";

describe("LiveOverview", () => {
  it("identifies HTTP fallback without presenting it as a live connection", () => {
    const markup = renderToStaticMarkup(
      <LiveOverview servers={[]} connection="fallback" updatedAt={0} />,
    );

    expect(markup).toContain("Aggiornamento periodico");
    expect(markup).toContain("Periodico");
    expect(markup).toContain(">HTTP<");
    expect(markup).not.toContain(">Connesso<");
  });
});
