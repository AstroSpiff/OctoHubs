import { useEffect, useState } from "react";

import { Button } from "@/components/ui/button";
import { DialogBackdrop } from "@/components/ui/dialog-backdrop";
import { useConfirmationDialog } from "@/components/ui/use-confirmation-dialog";
import type { IconProfile } from "@/features/user-icons/types";
import { useDirtyChange } from "@/lib/use-dirty-change";

type IconProfileDialogProps = {
  profile: IconProfile | null | undefined;
  open: boolean;
  saving: boolean;
  error?: string;
  onClose: () => void;
  onSave: (input: { id?: string; label: string; isGroupProfile: boolean }) => void;
  onDirtyChange?: (dirty: boolean) => void;
};

function IconProfileDialog({ profile, open, saving, error, onClose, onSave, onDirtyChange }: IconProfileDialogProps) {
  const confirmation = useConfirmationDialog();
  const [label, setLabel] = useState("");
  const [isGroupProfile, setIsGroupProfile] = useState(false);

  useEffect(() => {
    if (!open) return;
    setLabel(profile?.label || "");
    setIsGroupProfile(profile?.is_group_profile === true);
  }, [open, profile]);

  const dirty = label !== (profile?.label || "") || isGroupProfile !== (profile?.is_group_profile === true);
  useDirtyChange(open, dirty, onDirtyChange);

  if (!open) return null;

  function submit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const name = label.trim();
    if (name) onSave({ id: profile?.id, label: name, isGroupProfile });
  }

  async function requestClose() {
    if (saving) return;
    if (!dirty) {
      onClose();
      return;
    }
    const confirmed = await confirmation.confirm({
      title: "Profilo icona non salvato",
      description: "Chiudere e perdere le modifiche al profilo?",
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
      <form className="user-icons-profile-dialog" onSubmit={submit} role="dialog" aria-modal="true" aria-labelledby="icon-profile-dialog-title">
        <header>
          <h2 id="icon-profile-dialog-title" className="contextual-heading" title="Profili icona">{profile ? "Modifica profilo" : "Nuovo profilo"}</h2>
        </header>
        {error ? <p className="users-dialog-error" role="alert">{error}</p> : null}
        <label>
          Nome profilo
          <input autoFocus value={label} disabled={saving} onChange={(event) => setLabel(event.target.value)} />
        </label>
        <label className="user-icons-profile-kind">
          <input type="checkbox" checked={isGroupProfile} disabled={saving} onChange={(event) => setIsGroupProfile(event.target.checked)} />
          Profilo pensato per un gruppo di utenti
        </label>
        <footer>
          <Button type="button" variant="ghost" onClick={() => void requestClose()} disabled={saving}>Annulla</Button>
          <Button type="submit" variant="primary" disabled={!label.trim() || saving}>{saving ? "Salvataggio..." : "Salva profilo"}</Button>
        </footer>
      </form>
    </DialogBackdrop>
    {confirmation.dialog}
    </>
  );
}

export { IconProfileDialog };
