import {
  libraryItemIsSelected,
  removeUnresolvedLibraryAccessId,
  selectedLibraryAccessIds,
  setLibraryAccessMode,
  toggleLibraryAccessItem,
  unresolvedLibraryAccessIds,
} from "@/features/user-settings/library-access-state";
import type { LibrarySettingItem, UserSettings } from "@/features/user-settings/types";

function SettingsLibraryAccess({ settings, items, disabled, onChange }: { settings: UserSettings; items: LibrarySettingItem[]; disabled: boolean; onChange: (settings: UserSettings["libraries"]) => void }) {
  const custom = settings.libraries.mode === "custom";
  const selectedIds = selectedLibraryAccessIds(settings.libraries);
  const unresolvedIds = unresolvedLibraryAccessIds(settings.libraries, items);

  return <section className="user-settings-libraries"><header><div><strong>Accesso librerie</strong><small>La modalità personalizzata parte da tutte le librerie e consente di rimuovere solo quelle non accessibili.</small></div><label><input type="radio" name="library-mode" checked={!custom} disabled={disabled} onChange={() => onChange(setLibraryAccessMode(settings.libraries, items, "all"))} />Tutte</label><label><input type="radio" name="library-mode" checked={custom} disabled={disabled} onChange={() => onChange(setLibraryAccessMode(settings.libraries, items, "custom"))} />Personalizzato</label></header><div className={`user-settings-library-list ${custom ? "" : "is-readonly"}`}>{items.map((item) => { const label = `${item.name || item.id} (${item.collection_type || "Libreria"})`; return <label key={item.id}><input type="checkbox" checked={custom ? libraryItemIsSelected(item, selectedIds) : true} disabled={disabled || !custom} onChange={(event) => onChange(toggleLibraryAccessItem(settings.libraries, items, item, event.target.checked))} /><span><strong title={label}>{label}</strong>{item.group_key ? <small title="Questa libreria appartiene a un gruppo sincronizzabile.">Gruppo</small> : null}</span></label>; })}{unresolvedIds.map((id) => <label key={id} className="is-unresolved"><input type="checkbox" checked disabled={disabled} onChange={(event) => { if (!event.target.checked) onChange(removeUnresolvedLibraryAccessId(settings.libraries, items, id)); }} /><span><strong title={id}>ID: {id}</strong><small>Non disponibile su questo server</small></span></label>)}</div><small className="user-settings-library-access-hint">Le librerie con badge Gruppo si sincronizzano tra server. Le altre restano locali.</small></section>;
}

export { SettingsLibraryAccess };
