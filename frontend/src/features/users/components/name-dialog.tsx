import { useEffect, useState } from "react";

import { Button } from "@/components/ui/button";
import { DialogBackdrop } from "@/components/ui/dialog-backdrop";
import { useConfirmationDialog } from "@/components/ui/use-confirmation-dialog";
import { useDirtyChange } from "@/lib/use-dirty-change";

type NameDialogProps = {
  open: boolean;
  title: string;
  label: string;
  initialValue: string;
  saving: boolean;
  onClose: () => void;
  onSave: (value: string) => void;
  onDirtyChange?: (dirty: boolean) => void;
};

function NameDialog({
  open,
  title,
  label,
  initialValue,
  saving,
  onClose,
  onSave,
  onDirtyChange,
}: NameDialogProps) {
  const confirmation = useConfirmationDialog();
  const [value, setValue] = useState("");

  useEffect(() => {
    if (open) setValue(initialValue);
  }, [initialValue, open]);

  const dirty = value.trim() !== initialValue;
  useDirtyChange(open, dirty, onDirtyChange);

  if (!open) return null;

  function submit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const next = value.trim();
    if (next && next !== initialValue) onSave(next);
    else onClose();
  }

  async function requestClose() {
    if (saving) return;
    if (!dirty) {
      onClose();
      return;
    }
    const confirmed = await confirmation.confirm({
      title: "Rinomina non salvata",
      description: "Chiudere e perdere il nuovo nome inserito?",
      confirmLabel: "Abbandona modifiche",
      tone: "danger",
    });
    if (confirmed) onClose();
  }

  return (
    <>
    <DialogBackdrop
      className="users-dialog-backdrop"
      dismissible={!saving}
      onDismiss={() => void requestClose()}
    >
      <form
        className="users-compact-dialog"
        onSubmit={submit}
        role="dialog"
        aria-modal="true"
        aria-labelledby="name-dialog-title"
      >
        <header>
          <h2 id="name-dialog-title" className="contextual-heading" title="Gestione utenti">{title}</h2>
        </header>
        <label>
          {label}
          <input
            autoFocus
            value={value}
            disabled={saving}
            onChange={(event) => setValue(event.target.value)}
          />
        </label>
        <footer>
          <Button type="button" variant="ghost" onClick={() => void requestClose()} disabled={saving}>
            Annulla
          </Button>
          <Button type="submit" variant="primary" disabled={!value.trim() || saving}>
            {saving ? "Salvataggio..." : "Salva"}
          </Button>
        </footer>
      </form>
    </DialogBackdrop>
    {confirmation.dialog}
    </>
  );
}

export { NameDialog };
