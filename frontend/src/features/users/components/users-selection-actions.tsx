import { CopyPlus, Link2, SlidersHorizontal } from "@/components/ui/icons";

import { Button } from "@/components/ui/button";
import { WriteAction } from "@/features/session/workspace-capabilities";

type UsersSelectionActionsProps = {
  selectedCount: number;
  hiddenCount: number;
  onLink: () => void;
  onBulkSettings: () => void;
  onBulkClone: () => void;
  onDeselect: () => void;
};

function UsersSelectionActions({ selectedCount, hiddenCount, onLink, onBulkSettings, onBulkClone, onDeselect }: UsersSelectionActionsProps) {
  if (!selectedCount) return null;

  return (
    <WriteAction>
      <section className="users-selection-summary" aria-label="Azioni per utenti selezionati">
        <p>
          <strong>{selectedCount}</strong> {selectedCount === 1 ? "utente selezionato" : "utenti selezionati"}
          {hiddenCount ? <small>{hiddenCount === 1 ? "1 nascosto dal filtro" : `${hiddenCount} nascosti dal filtro`}</small> : null}
        </p>
        <div className="users-selection-summary-actions">
          <Button type="button" variant="ghost" size="compact" onClick={onDeselect}>Annulla</Button>
          <span className="users-selection-divider" aria-hidden="true" />
          <Button type="button" variant="secondary" onClick={onLink} disabled={selectedCount < 2}>
            <Link2 size={16} aria-hidden="true" />
            Associa
          </Button>
          <Button type="button" variant="primary" onClick={onBulkSettings}>
            <SlidersHorizontal size={16} aria-hidden="true" />
            Applica impostazioni
          </Button>
          <Button type="button" variant="primary" onClick={onBulkClone}>
            <CopyPlus size={16} aria-hidden="true" />
            Clona
          </Button>
        </div>
      </section>
    </WriteAction>
  );
}

export { UsersSelectionActions };
