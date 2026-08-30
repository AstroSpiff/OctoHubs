import type { LatestRuleInput } from "@/features/emby-latest/types";

function emptyLatestRuleInput(): LatestRuleInput {
  return {
    name: "",
    server_ids: [],
    preset_id: "",
    telegram_config_id: "",
  };
}

function copyLatestRuleInput(input: LatestRuleInput): LatestRuleInput {
  return {
    ...input,
    server_ids: [...input.server_ids],
  };
}

function latestRuleInputMatches(
  first: LatestRuleInput,
  second: LatestRuleInput,
) {
  return (
    first.id === second.id &&
    first.name === second.name &&
    first.preset_id === second.preset_id &&
    first.telegram_config_id === second.telegram_config_id &&
    sameIds(first.server_ids, second.server_ids)
  );
}

function sameIds(first: string[], second: string[]) {
  return first.length === second.length && first.every((id) => second.includes(id));
}

export {
  copyLatestRuleInput,
  emptyLatestRuleInput,
  latestRuleInputMatches,
};
