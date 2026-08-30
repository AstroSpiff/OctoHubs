import { describe, expect, it } from "vitest";

import {
  telegramBotDraftIsDirty,
  telegramChatDraftIsDirty,
  telegramPresetDraftIsDirty,
} from "@/features/configuration/telegram-draft";
import type { TelegramBot, TelegramChat, TelegramPreset } from "@/features/configuration/types";

const bot = { id: "bot-1", alias: "Notifiche", token_configured: true } as TelegramBot;
const chat = { id: "chat-1", alias: "Gruppo film", chat_id: "-1001" } as TelegramChat;
const preset = {
  id: "preset-1",
  name: "Film",
  bot_ids: ["bot-1"],
  group_ids: ["group-1", "group-2"],
  channel_ids: ["channel-1"],
} as TelegramPreset;

describe("Telegram drafts", () => {
  it("keeps an untouched bot editor clean but treats a replacement token as a change", () => {
    expect(telegramBotDraftIsDirty(bot, { alias: "Notifiche", token: "" })).toBe(false);
    expect(telegramBotDraftIsDirty(bot, { alias: "Notifiche", token: "new-token" })).toBe(true);
  });

  it("compares chat fields and ignores an editor that is closed", () => {
    expect(telegramChatDraftIsDirty(chat, { alias: "Gruppo film", chatId: "-1001" })).toBe(false);
    expect(telegramChatDraftIsDirty(chat, { alias: "Gruppo serie", chatId: "-1001" })).toBe(true);
    expect(telegramChatDraftIsDirty(null, { alias: "", chatId: "" })).toBe(false);
  });

  it("compares preset destinations as sets because checkbox order has no meaning", () => {
    expect(telegramPresetDraftIsDirty(preset, {
      name: "Film",
      botId: "bot-1",
      groupIds: ["group-2", "group-1"],
      channelIds: ["channel-1"],
    })).toBe(false);
    expect(telegramPresetDraftIsDirty(preset, {
      name: "Film",
      botId: "bot-1",
      groupIds: ["group-1"],
      channelIds: ["channel-1"],
    })).toBe(true);
  });
});
