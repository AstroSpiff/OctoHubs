import type { EmbyUserServer } from "@/features/users/types";

type CreateUserDraft = {
  linkGroup: boolean;
  password: string;
  presetId: string;
  serverIds: string[];
  username: string;
};

function createUserDraft(servers: EmbyUserServer[]): CreateUserDraft {
  return {
    username: "",
    password: "",
    serverIds: servers.map((server) => server.id),
    linkGroup: true,
    presetId: "",
  };
}

function createUserDraftMatches(
  first: CreateUserDraft,
  second: CreateUserDraft,
) {
  return (
    first.username === second.username &&
    first.password === second.password &&
    first.linkGroup === second.linkGroup &&
    first.presetId === second.presetId &&
    sameIds(first.serverIds, second.serverIds)
  );
}

function sameIds(first: string[], second: string[]) {
  return first.length === second.length && first.every((id) => second.includes(id));
}

export { createUserDraft, createUserDraftMatches };
export type { CreateUserDraft };
