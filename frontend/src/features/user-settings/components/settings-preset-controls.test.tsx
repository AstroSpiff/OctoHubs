// @vitest-environment jsdom

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { getSettingsPresets } from "@/features/user-settings/api";
import { SettingsPresetControls } from "@/features/user-settings/components/settings-preset-controls";
import type { SettingsPreset, UserSettings } from "@/features/user-settings/types";

vi.mock("@/features/user-settings/api", () => ({
  deleteSettingsPreset: vi.fn(),
  duplicateSettingsPreset: vi.fn(),
  getSettingsPreset: vi.fn(),
  getSettingsPresets: vi.fn(),
  saveSettingsPreset: vi.fn(),
}));
vi.mock("@/lib/use-application-event", () => ({
  useApplicationEventRefresh: vi.fn(),
}));

declare global {
  var IS_REACT_ACT_ENVIRONMENT: boolean | undefined;
}

const preset: SettingsPreset = {
  id: "cinema",
  label: "Cinema",
  settings: {},
};

describe("SettingsPresetControls reconciliation", () => {
  let container: HTMLDivElement;
  let root: ReturnType<typeof createRoot>;
  let client: QueryClient;

  beforeEach(() => {
    globalThis.IS_REACT_ACT_ENVIRONMENT = true;
    vi.mocked(getSettingsPresets).mockResolvedValue({
      ok: true,
      presets: [preset],
    });
    client = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
    container = document.createElement("div");
    document.body.append(container);
    root = createRoot(container);
  });

  afterEach(() => {
    act(() => root.unmount());
    container.remove();
    client.clear();
    vi.resetAllMocks();
    globalThis.IS_REACT_ACT_ENVIRONMENT = undefined;
  });

  it("clears a selection removed by a realtime-refetched snapshot", async () => {
    await act(async () => {
      root.render(
        <QueryClientProvider client={client}>
          <SettingsPresetControls
            settings={{} as UserSettings}
            applyLibraries
            disabled={false}
            onLoad={vi.fn()}
          />
        </QueryClientProvider>,
      );
      await Promise.resolve();
    });
    const select = container.querySelector<HTMLSelectElement>(
      '[aria-label="Preset salvati"]',
    );
    await act(async () => {
      await vi.waitFor(() => expect(select?.options.length).toBe(2));
    });
    act(() => {
      const setValue = Object.getOwnPropertyDescriptor(
        HTMLSelectElement.prototype,
        "value",
      )?.set;
      setValue?.call(select, preset.id);
      select?.dispatchEvent(new Event("change", { bubbles: true }));
    });
    expect(select?.value).toBe(preset.id);

    act(() => {
      client.setQueryData(["user-settings-presets"], {
        ok: true,
        presets: [],
      });
    });

    await act(async () => {
      await vi.waitFor(() => expect(select?.value).toBe(""));
    });
    const update = Array.from(container.querySelectorAll("button")).find(
      (button) => button.textContent?.includes("Aggiorna"),
    );
    expect(update?.disabled).toBe(true);
  });
});
