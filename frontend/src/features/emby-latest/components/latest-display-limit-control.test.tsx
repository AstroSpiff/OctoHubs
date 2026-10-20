import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { LatestDisplayLimitControl } from "@/features/emby-latest/components/latest-display-limit-control";

describe("LatestDisplayLimitControl", () => {
  it("keeps database limits compact without losing their accessible meaning", () => {
    const markup = renderToStaticMarkup(
      <LatestDisplayLimitControl
        displayLimit={10}
        maxMovies={50}
        maxSeries={25}
        onLimitChange={() => undefined}
      />,
    );

    expect(markup).toContain("50 film · 25 serie");
    expect(markup).toContain("Limiti database: 50 film · 25 serie");
    expect(markup).not.toContain("Max DB:");
  });
});
