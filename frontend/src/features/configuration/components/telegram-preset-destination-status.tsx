import { CheckCircle2, CircleAlert, CircleEllipsis, CircleX } from "@/components/ui/icons";

import { telegramAlertPresentation } from "@/features/configuration/telegram-preset-presentation";
import type { TelegramChat, TelegramPreset } from "@/features/configuration/types";

function TelegramPresetDestinationStatus({
  ids,
  entries,
  kind,
  alerts,
}: {
  ids: string[];
  entries: TelegramChat[];
  kind: "groups" | "channels";
  alerts: TelegramPreset["alerts"];
}) {
  if (!ids.length) return <>-</>;

  return <span className="telegram-preset-destinations">{ids.map((id) => {
    const entry = entries.find((item) => item.id === id);
    const name = entry?.alias || entry?.original_name || entry?.chat_id || id;
    const presentation = telegramAlertPresentation(alerts[kind]?.[id]?.[0]);
    const Icon = presentation.severity === "ok" ? CheckCircle2 : presentation.severity === "error" ? CircleX : presentation.severity === "warning" ? CircleAlert : CircleEllipsis;
    return <span key={id} className="telegram-preset-destination"><span>{name}</span><span className={`telegram-preset-destination-status telegram-preset-destination-status--${presentation.severity}`} title={presentation.detail}><Icon size={13} aria-hidden="true" />{presentation.label}</span></span>;
  })}</span>;
}

export { TelegramPresetDestinationStatus };
