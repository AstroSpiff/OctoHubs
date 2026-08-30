import { describe, expect, it } from "vitest";

import {
  copyLatestPresetInput,
  emptyLatestPresetInput,
  latestPresetInputFromPreset,
  latestPresetInputMatches,
} from "@/features/emby-latest/latest-preset-draft";

describe("latest preset draft", () => {
  it("creates a blank independent draft for a new preset", () => {
    const preset = emptyLatestPresetInput();
    const copy = copyLatestPresetInput(preset);

    copy.name = "Notifiche";
    expect(preset).toEqual({ name: "", template: "" });
  });

  it("compares the editable preset fields and preserves the source preset", () => {
    const source = { id: "public", name: "Canale pubblico", template: "{{ title }}" };
    const draft = latestPresetInputFromPreset(source);

    expect(latestPresetInputMatches(draft, source)).toBe(true);
    expect(latestPresetInputMatches(draft, { ...source, template: "{{ year }}" })).toBe(false);
  });
});
