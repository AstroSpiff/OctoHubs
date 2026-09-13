// @vitest-environment jsdom

import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { LatestPresetManager } from "@/features/emby-latest/components/latest-preset-manager";
import type { LatestPresetInput } from "@/features/emby-latest/types";

declare global {
  var IS_REACT_ACT_ENVIRONMENT: boolean | undefined;
}

const presets = [
  { id: "main", name: "Principale", template: "Principale {{ title }}" },
  { id: "compact", name: "Compatto", template: "Compatto {{ title }}" },
];

describe("LatestPresetManager preview selection", () => {
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

  it("selects a saved preset for preview without opening the editor", async () => {
    const onSelectPreset = vi.fn();
    const drafts: Array<LatestPresetInput | null> = [];
    await act(async () => {
      root.render(
        <LatestPresetManager
          presets={presets}
          selectedPresetId="main"
          saving={false}
          onSave={async () => undefined}
          onRemove={() => undefined}
          onSelectPreset={onSelectPreset}
          onDraftChange={(draft) => drafts.push(draft)}
        />,
      );
    });

    const selectButton = container.querySelector<HTMLButtonElement>(
      'button[aria-label="Mostra anteprima Compatto"]',
    );
    await act(async () => selectButton?.click());

    expect(onSelectPreset).toHaveBeenCalledWith("compact");
    expect(drafts.at(-1)).toBeNull();
    expect(container.querySelector<HTMLTextAreaElement>("textarea")?.value).toBe("");
  });

  it("uses the edited draft as preview source", async () => {
    const onSelectPreset = vi.fn();
    const onDraftChange = vi.fn();
    await act(async () => {
      root.render(
        <LatestPresetManager
          presets={presets}
          selectedPresetId="main"
          saving={false}
          onSave={async () => undefined}
          onRemove={() => undefined}
          onSelectPreset={onSelectPreset}
          onDraftChange={onDraftChange}
        />,
      );
    });

    const editButton = container.querySelector<HTMLButtonElement>(
      'button[title="Modifica Compatto"]',
    );
    await act(async () => editButton?.click());

    expect(onSelectPreset).toHaveBeenCalledWith("compact");
    expect(onDraftChange).toHaveBeenLastCalledWith({
      id: "compact",
      name: "Compatto",
      template: "Compatto {{ title }}",
    });

    const textarea = container.querySelector<HTMLTextAreaElement>("textarea");
    await act(async () => {
      const setter = Object.getOwnPropertyDescriptor(
        HTMLTextAreaElement.prototype,
        "value",
      )?.set;
      setter?.call(textarea, "Bozza {{ title }}");
      textarea?.dispatchEvent(new Event("input", { bubbles: true }));
    });

    expect(onDraftChange).toHaveBeenLastCalledWith({
      id: "compact",
      name: "Compatto",
      template: "Bozza {{ title }}",
    });
  });
});
