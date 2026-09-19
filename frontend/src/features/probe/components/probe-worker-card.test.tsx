import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";

import { ProbeWorkerCard } from "@/features/probe/components/probe-worker-card";

const action = {
  label: "Avvia",
  icon: "play" as const,
  onClick: vi.fn(),
};

describe("ProbeWorkerCard", () => {
  it("mostra l'avanzamento soltanto mentre il worker e in esecuzione", () => {
    const markup = renderToStaticMarkup(
      <ProbeWorkerCard
        title="Analisi"
        description="Descrizione"
        status={{ running: true }}
        progress={{ completed: 5, total: 10 }}
        actions={[action]}
      />,
    );

    expect(markup).toContain("probe-worker-progress");
    expect(markup).toContain("50%");
    expect(markup).not.toContain("5/10");
  });

  it("nasconde un avanzamento residuo dopo lo stop", () => {
    const markup = renderToStaticMarkup(
      <ProbeWorkerCard
        title="Analisi"
        description="Descrizione"
        status={{ running: false, processed: 5, total: 10 }}
        progress={{ completed: 5, total: 10 }}
        actions={[action]}
      />,
    );

    expect(markup).not.toContain("probe-worker-progress");
    expect(markup).not.toContain("5/10");
    expect(markup).toContain("Pronto per l&#x27;avvio");
  });
});
