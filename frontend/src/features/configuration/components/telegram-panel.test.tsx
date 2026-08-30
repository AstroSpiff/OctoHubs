import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";

import { TelegramPanel } from "@/features/configuration/components/telegram-panel";

describe("TelegramPanel", () => {
  it("shows the settings query error before the loading fallback", () => {
    const markup = renderToStaticMarkup(
      <TelegramPanel
        busy={false}
        notice=""
        actionError=""
        loadError={new Error("Telegram non raggiungibile")}
        retrying={false}
        onAction={vi.fn()}
        onRetry={vi.fn()}
      />,
    );

    expect(markup).toContain("Telegram non raggiungibile");
    expect(markup).toContain("Riprova");
    expect(markup).not.toContain("Caricamento configurazione Telegram");
  });
});
