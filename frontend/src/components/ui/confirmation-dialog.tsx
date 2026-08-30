import { AlertTriangle, CircleAlert } from "@/components/ui/icons";

import { Button } from "@/components/ui/button";
import { DialogBackdrop } from "@/components/ui/dialog-backdrop";

type ConfirmationTone = "danger" | "primary";

type ConfirmationOptions = {
  title: string;
  description: string;
  confirmLabel?: string;
  tone?: ConfirmationTone;
};

type ConfirmationDialogProps = ConfirmationOptions & {
  open: boolean;
  onCancel: () => void;
  onConfirm: () => void;
};

function ConfirmationDialog({
  open,
  title,
  description,
  confirmLabel = "Conferma",
  tone = "primary",
  onCancel,
  onConfirm,
}: ConfirmationDialogProps) {
  if (!open) return null;

  const Icon = tone === "danger" ? AlertTriangle : CircleAlert;

  return (
    <DialogBackdrop
      className="confirmation-dialog-backdrop"
      onDismiss={onCancel}
    >
      <section
        className={`confirmation-dialog confirmation-dialog--${tone}`}
        role="alertdialog"
        aria-modal="true"
        aria-labelledby="confirmation-dialog-title"
        aria-describedby="confirmation-dialog-description"
      >
        <span className="confirmation-dialog-icon" aria-hidden="true">
          <Icon size={20} />
        </span>
        <div className="confirmation-dialog-copy">
          <h2 id="confirmation-dialog-title">{title}</h2>
          <p id="confirmation-dialog-description">{description}</p>
        </div>
        <footer>
          <Button
            autoFocus
            type="button"
            variant="secondary"
            onClick={onCancel}
          >
            Annulla
          </Button>
          <Button type="button" variant={tone} onClick={onConfirm}>
            {confirmLabel}
          </Button>
        </footer>
      </section>
    </DialogBackdrop>
  );
}

export { ConfirmationDialog };
export type { ConfirmationOptions, ConfirmationTone };
