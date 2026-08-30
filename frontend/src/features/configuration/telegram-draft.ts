import type { TelegramBot, TelegramChat, TelegramPreset } from "@/features/configuration/types";

type TelegramBotDraft = {
  alias: string;
  token: string;
};

type TelegramChatDraft = {
  alias: string;
  chatId: string;
};

type TelegramPresetDraft = {
  name: string;
  botId: string;
  groupIds: string[];
  channelIds: string[];
};

function sameIdSet(left: string[], right: string[]) {
  return left.length === right.length && left.every((id) => right.includes(id));
}

function telegramBotDraftIsDirty(editing: TelegramBot | null, draft: TelegramBotDraft) {
  if (!editing) return false;
  return draft.alias !== (editing.alias || "") || Boolean(draft.token);
}

function telegramChatDraftIsDirty(editing: TelegramChat | null, draft: TelegramChatDraft) {
  if (!editing) return false;
  return draft.alias !== (editing.alias || "") || draft.chatId !== (editing.chat_id || "");
}

function telegramPresetDraftIsDirty(editing: TelegramPreset | null, draft: TelegramPresetDraft) {
  if (!editing) return false;
  return draft.name !== (editing.name || "")
    || draft.botId !== (editing.bot_ids?.[0] || "")
    || !sameIdSet(draft.groupIds, editing.group_ids || [])
    || !sameIdSet(draft.channelIds, editing.channel_ids || []);
}

export {
  telegramBotDraftIsDirty,
  telegramChatDraftIsDirty,
  telegramPresetDraftIsDirty,
};
export type { TelegramBotDraft, TelegramChatDraft, TelegramPresetDraft };
