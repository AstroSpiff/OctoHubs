import { ArrowDown, ArrowUp, Plus, Trash2 } from "@/components/ui/icons";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import { libraryIdentityIds, libraryItemIsSelected } from "@/features/user-settings/library-multi-selection";
import {
  moveLibraryOrderItem,
  normalizeLibraryOrder,
  removeLibraryOrderItem,
} from "@/features/user-settings/library-order-state";
import type {
  LibrarySettingItem,
  SettingsField,
} from "@/features/user-settings/types";

type SettingsLibraryOrderFieldProps = {
  field: SettingsField;
  value: unknown;
  items: LibrarySettingItem[];
  disabled: boolean;
  onChange: (value: string[]) => void;
};

function SettingsLibraryOrderField({
  field,
  value,
  items,
  disabled,
  onChange,
}: SettingsLibraryOrderFieldProps) {
  const [pendingLibraryId, setPendingLibraryId] = useState("");
  const order = normalizeLibraryOrder(value);
  const selectedIds = new Set(order);
  const itemById = new Map(items.flatMap((item) => libraryIdentityIds(item).map((id) => [id, item] as const)));
  const availableItems = items.filter((item) => !libraryItemIsSelected(item, selectedIds));

  function addLibrary() {
    if (!pendingLibraryId) return;
    onChange([...order, pendingLibraryId]);
    setPendingLibraryId("");
  }

  return (
    <section className="user-settings-field user-settings-library-order">
      <header>
        <strong>{field.label || field.key}</strong>
        {field.description ? <small>{field.description}</small> : null}
      </header>
      {order.length ? (
        <div className="user-settings-library-order-list">
          {order.map((id, index) => {
            const item = itemById.get(id);
            const itemLabel = item
              ? `${item.name || item.id} (${item.collection_type || "Libreria"})`
              : `ID: ${id}`;
            return (
              <div key={`${id}:${index}`} className="user-settings-library-order-row">
                <span>
                  <strong title={itemLabel}>{itemLabel}</strong>
                  {item?.group_key ? (
                    <small title="Questa libreria appartiene a un gruppo sincronizzabile.">
                      Gruppo
                    </small>
                  ) : null}
                </span>
                <div>
                  <Button type="button" variant="ghost" size="icon" title={`Sposta ${itemLabel} in alto`} aria-label={`Sposta ${itemLabel} in alto`} disabled={disabled || index === 0} onClick={() => onChange(moveLibraryOrderItem(order, index, -1))}>
                    <ArrowUp size={15} aria-hidden="true" />
                  </Button>
                  <Button type="button" variant="ghost" size="icon" title={`Sposta ${itemLabel} in basso`} aria-label={`Sposta ${itemLabel} in basso`} disabled={disabled || index === order.length - 1} onClick={() => onChange(moveLibraryOrderItem(order, index, 1))}>
                    <ArrowDown size={15} aria-hidden="true" />
                  </Button>
                  <Button type="button" variant="ghost" size="icon" title={`Rimuovi ${itemLabel} dall'ordine`} aria-label={`Rimuovi ${itemLabel} dall'ordine`} disabled={disabled} onClick={() => onChange(removeLibraryOrderItem(order, index))}>
                    <Trash2 size={15} aria-hidden="true" />
                  </Button>
                </div>
              </div>
            );
          })}
        </div>
      ) : (
        <p className="user-settings-library-order-empty">Nessuna libreria ordinata.</p>
      )}
      {availableItems.length ? (
        <div className="user-settings-library-order-add">
          <select aria-label="Aggiungi libreria all'ordine" value={pendingLibraryId} disabled={disabled} onChange={(event) => setPendingLibraryId(event.target.value)}>
            <option value="">Seleziona libreria...</option>
            {availableItems.map((item) => <option key={item.id} value={item.id}>{item.name || item.id}</option>)}
          </select>
          <Button type="button" variant="secondary" size="icon" title="Aggiungi libreria all'ordine" aria-label="Aggiungi libreria all'ordine" disabled={disabled || !pendingLibraryId} onClick={addLibrary}>
            <Plus size={16} aria-hidden="true" />
          </Button>
        </div>
      ) : null}
      <small className="user-settings-library-order-hint">
        Le librerie con badge Gruppo si sincronizzano tra server. Le altre restano locali.
      </small>
    </section>
  );
}

export { SettingsLibraryOrderField };
