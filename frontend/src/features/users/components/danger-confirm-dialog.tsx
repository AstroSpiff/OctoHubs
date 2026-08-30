import { useEffect, useState } from "react";

import { Button } from "@/components/ui/button";
import { DialogBackdrop } from "@/components/ui/dialog-backdrop";

type DangerConfirmDialogProps = {
  open: boolean;
  title: string;
  description: string;
  expectedName: string;
  confirming: boolean;
  onClose: () => void;
  onConfirm: (expectedName: string) => void;
};

function DangerConfirmDialog({
  open,
  title,
  description,
  expectedName,
  confirming,
  onClose,
  onConfirm,
}: DangerConfirmDialogProps) {
  const [value, setValue] = useState("");

  useEffect(() => {
    if (open) setValue("");
  }, [open]);

  if (!open) return null;

  function submit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (value === expectedName) onConfirm(value);
  }

  return (
    <DialogBackdrop
      className="users-dialog-backdrop"
      dismissible={!confirming}
      onDismiss={onClose}
    >
      <form
        className="users-compact-dialog users-compact-dialog--danger"
        onSubmit={submit}
        role="dialog"
        aria-modal="true"
        aria-labelledby="danger-dialog-title"
      >
        <header>
          <h2 id="danger-dialog-title" className="contextual-heading" title="Azione irreversibile">{title}</h2>
        </header>
        <p className="users-danger-copy">{description}</p>
        <label>
          Digita <strong>{expectedName}</strong> per confermare
          <input
            autoFocus
            value={value}
            disabled={confirming}
            onChange={(event) => setValue(event.target.value)}
          />
        </label>
        <footer>
          <Button type="button" variant="ghost" onClick={onClose} disabled={confirming}>
            Annulla
          </Button>
          <Button type="submit" variant="danger" disabled={value !== expectedName || confirming}>
            {confirming ? "Eliminazione..." : "Elimina"}
          </Button>
        </footer>
      </form>
    </DialogBackdrop>
  );
}

export { DangerConfirmDialog };
