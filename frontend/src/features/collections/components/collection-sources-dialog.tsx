import { X } from "@/components/ui/icons";
import { useEffect, useState } from "react";

import { Button } from "@/components/ui/button";
import { DialogBackdrop } from "@/components/ui/dialog-backdrop";
import { useConfirmationDialog } from "@/components/ui/use-confirmation-dialog";
import { CollectionSourcesPanel } from "@/features/collections/components/collection-sources-panel";
import type { SourceSelection } from "@/features/collections/collection-source-selection";
import type { CollectionOptions } from "@/features/collections/types";

function CollectionSourcesDialog({
  open,
  options,
  onClose,
  onSelect,
  onDirtyChange,
}: {
  open: boolean;
  options?: CollectionOptions;
  onClose: () => void;
  onSelect: (selection: SourceSelection) => void;
  onDirtyChange?: (dirty: boolean) => void;
}) {
  const confirmation = useConfirmationDialog();
  const [inventoryDirty, setInventoryDirty] = useState(false);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    onDirtyChange?.(open && inventoryDirty);
    return () => onDirtyChange?.(false);
  }, [inventoryDirty, onDirtyChange, open]);

  useEffect(() => {
    if (!open) setInventoryDirty(false);
  }, [open]);

  if (!open) return null;

  async function choose(selection: SourceSelection) {
    setInventoryDirty(false);
    onSelect(selection);
    onClose();
  }

  async function requestClose() {
    if (busy) return;
    if (
      inventoryDirty &&
      !(await confirmation.confirm({
        title: "Fonte manuale non salvata",
        description: "Chiudere e perdere il riferimento manuale in corso?",
        confirmLabel: "Abbandona modifiche",
        tone: "danger",
      }))
    ) {
      return;
    }
    setInventoryDirty(false);
    onClose();
  }

  return (
    <DialogBackdrop
      className="users-dialog-backdrop"
      dismissible={!busy}
      onDismiss={() => void requestClose()}
    >
      <section
        className="collection-sources-dialog"
        role="dialog"
        aria-modal="true"
        aria-labelledby="collection-sources-title"
      >
        <header>
          <div>
            <h2 id="collection-sources-title" className="contextual-heading" title="Fonti collezioni">Liste personali e salvate</h2>
            <p>
              Scegli una lista per riempire la fonte dell&apos;editor, oppure
              conserva un riferimento manuale.
            </p>
          </div>
          <Button
            type="button"
            variant="ghost"
            size="icon"
            title="Chiudi fonti collezioni"
            aria-label="Chiudi fonti collezioni"
            onClick={() => void requestClose()}
            disabled={busy}
          >
            <X size={17} aria-hidden="true" />
          </Button>
        </header>
        <CollectionSourcesPanel
          enabled={open}
          options={options}
          onSelect={(selection) => void choose(selection)}
          onDirtyChange={setInventoryDirty}
          onBusyChange={setBusy}
        />
      </section>
      {confirmation.dialog}
    </DialogBackdrop>
  );
}

export { CollectionSourcesDialog };
