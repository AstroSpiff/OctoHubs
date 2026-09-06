// @vitest-environment jsdom

import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ServiceSettingsPanel } from "@/features/configuration/components/service-settings-panel";
import type { ConfigurationServices, ConnectionCheckPayload } from "@/features/configuration/types";

declare global {
  var IS_REACT_ACT_ENVIRONMENT: boolean | undefined;
}

const services: ConfigurationServices = {
  database: { enabled: true, host: "db", port: "5432", name: "octohubs", user: "octohubs", driver: "postgresql+psycopg2", url_configured: false, params: "", password_configured: true },
  connections: {
    jellyseerr: { url: "http://jellyseerr:5055", api_key_configured: true },
    prowlarr: { url: "", api_key_configured: false },
    jackett: { url: "", api_key_configured: false },
    qbittorrent: { url: "", username: "", api_key_configured: false, password_configured: false },
    tmdb: { language: "it-IT", api_key_configured: true },
    mdblist: { api_keys_configured: 0 },
    omdb: { api_keys_configured: 0 },
  },
  trakt: { enabled: false, client_id: "", client_secret_configured: false, access_token_configured: false, refresh_token_configured: false, expires_at: "" },
  justwatch: { enabled: false, locale: "it_IT" },
};

describe("ServiceSettingsPanel connection checks", () => {
  let container: HTMLDivElement;
  let root: ReturnType<typeof createRoot>;

  beforeEach(() => {
    globalThis.IS_REACT_ACT_ENVIRONMENT = true;
    container = document.createElement("div");
    document.body.append(container);
    root = createRoot(container);
  });

  afterEach(() => {
    act(() => root.unmount());
    container.remove();
    globalThis.IS_REACT_ACT_ENVIRONMENT = undefined;
  });

  it("checks only saved settings and never displays a result made stale by a draft", async () => {
    let resolveCheck: ((payload: ConnectionCheckPayload) => void) | undefined;
    const onTestConnections = vi.fn(() => new Promise<ConnectionCheckPayload>((resolve) => {
      resolveCheck = resolve;
    }));

    await act(async () => {
      root.render(
        <ServiceSettingsPanel
          services={services}
          saving={false}
          savedMessage=""
          onSave={vi.fn()}
          onTestConnections={onTestConnections}
          onRefreshSettings={vi.fn()}
          onNotice={vi.fn()}
        />,
      );
    });

    const checkButton = buttonWithText(container, "Verifica connessioni");
    act(() => checkButton.click());
    expect(onTestConnections).toHaveBeenCalledTimes(1);

    const urlInput = container.querySelector<HTMLInputElement>('input[type="url"]');
    act(() => {
      setInputValue(urlInput, "http://draft-only:5055");
    });

    expect(checkButton.disabled).toBe(true);
    expect(checkButton.title).toContain("Salva o ripristina");

    await act(async () => {
      resolveCheck?.({
        success: true,
        statuses: { jellyseerr: { ok: true, message: "Risultato della configurazione precedente" } },
      });
      await Promise.resolve();
    });

    expect(container.textContent).not.toContain("Risultato della configurazione precedente");
    act(() => buttonWithText(container, "Ripristina valori salvati").click());
    expect(checkButton.disabled).toBe(false);
    expect(container.textContent).not.toContain("Risultato della configurazione precedente");
  });
});

function buttonWithText(container: HTMLElement, text: string) {
  const button = [...container.querySelectorAll<HTMLButtonElement>("button")]
    .find((candidate) => candidate.textContent?.includes(text));
  if (!button) throw new Error(`Button not found: ${text}`);
  return button;
}

function setInputValue(input: HTMLInputElement | null, value: string) {
  if (!input) throw new Error("Input not found");
  const setValue = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")?.set;
  setValue?.call(input, value);
  input.dispatchEvent(new Event("input", { bubbles: true }));
}
