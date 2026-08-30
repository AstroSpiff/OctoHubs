import {
  formatSettingsUpdatedAt,
  settingsEditorStatus,
} from "@/features/user-settings/settings-editor-status";
import type { SettingsInfo, SettingsTarget } from "@/features/user-settings/types";

function SettingsEditorStatus({
  target,
  info,
}: {
  target: SettingsTarget;
  info: SettingsInfo | null;
}) {
  if (!info) return null;
  const status = settingsEditorStatus(target, info);
  const updatedAt = formatSettingsUpdatedAt(info.updated_at);

  return (
    <div className="user-settings-status" aria-live="polite">
      <span className={`user-settings-status__badge user-settings-status__badge--${status.tone}`}>
        {status.label}
      </span>
      {updatedAt ? <span>Ultimo aggiornamento: {updatedAt}</span> : null}
    </div>
  );
}

export { SettingsEditorStatus };
