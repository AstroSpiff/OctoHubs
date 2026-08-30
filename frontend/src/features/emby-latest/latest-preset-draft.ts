import type { LatestPreset, LatestPresetInput } from "@/features/emby-latest/types";

function emptyLatestPresetInput(): LatestPresetInput {
  return { name: "", template: "" };
}

function latestPresetInputFromPreset(preset: LatestPreset): LatestPresetInput {
  return { id: preset.id, name: preset.name, template: preset.template };
}

function copyLatestPresetInput(input: LatestPresetInput): LatestPresetInput {
  return { ...input };
}

function latestPresetInputMatches(first: LatestPresetInput, second: LatestPresetInput): boolean {
  return first.id === second.id && first.name === second.name && first.template === second.template;
}

export {
  copyLatestPresetInput,
  emptyLatestPresetInput,
  latestPresetInputFromPreset,
  latestPresetInputMatches,
};
