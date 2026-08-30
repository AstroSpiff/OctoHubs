import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { StatusBadge } from "@/components/ui/badge";

describe("StatusBadge", () => {
  it("keeps informational and neutral states distinct from warnings", () => {
    const informational = renderToStaticMarkup(
      <StatusBadge severity="info">Aggiornamento periodico</StatusBadge>,
    );
    const neutral = renderToStaticMarkup(
      <StatusBadge severity="neutral">Uscito</StatusBadge>,
    );

    expect(informational).toContain("--color-info-border");
    expect(neutral).toContain("--color-surface-muted");
  });
});
