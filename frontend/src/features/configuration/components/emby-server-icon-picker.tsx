import { Server } from "@/components/ui/icons";
import { useId } from "react";

import { iconColorPresets, iconOptions, iconSuggestions } from "@/features/configuration/emby-server-icon-catalog";

function EmbyServerIconPicker({
  icon,
  color,
  disabled,
  onIconChange,
  onColorChange,
}: {
  icon: string;
  color: string;
  disabled: boolean;
  onIconChange: (value: string) => void;
  onColorChange: (value: string) => void;
}) {
  const suggestionsId = useId();
  const selected = iconOptions.find((option) => option.value === icon);
  const PreviewIcon = selected?.Icon || Server;

  return <div className="configuration-icon-picker">
    <span className="configuration-icon-preview" style={{ color }} title={icon}><PreviewIcon size={20} aria-hidden="true" /></span>
    <label><span>Icona</span><input list={suggestionsId} value={icon} disabled={disabled} onChange={(event) => onIconChange(event.target.value)} placeholder="fa-server" aria-label="Classe Font Awesome dell'icona" /><datalist id={suggestionsId}>{iconSuggestions.map((value) => <option key={value} value={value} />)}</datalist></label>
    <label><span>Colore</span><input type="color" value={color} disabled={disabled} onChange={(event) => onColorChange(event.target.value)} aria-label="Colore icona" /></label>
    <div className="configuration-icon-colors" aria-label="Colori rapidi">{iconColorPresets.map((preset) => <button key={preset} type="button" className={preset.toLowerCase() === color.toLowerCase() ? "is-active" : ""} style={{ backgroundColor: preset }} title={`Usa ${preset}`} aria-label={`Usa colore ${preset}`} aria-pressed={preset.toLowerCase() === color.toLowerCase()} disabled={disabled} onClick={() => onColorChange(preset)} />)}</div>
  </div>;
}

export { EmbyServerIconPicker };
