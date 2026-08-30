import { useEffect, useMemo, useState } from "react";

import { Button } from "@/components/ui/button";
import { DialogBackdrop } from "@/components/ui/dialog-backdrop";
import { useConfirmationDialog } from "@/components/ui/use-confirmation-dialog";
import { useDirtyChange } from "@/lib/use-dirty-change";
import { hasDifferentLinkNames, linkTargetGroups, needsLinkTargetChoice, preferredLinkLeaderKey } from "@/features/users/link-user-association";
import { ServerIdentity } from "@/features/users/components/server-identity";
import { userSelectionKey } from "@/features/users/presentation";
import type { LinkUserSelection, LinkUsersInput } from "@/features/users/types";

const newGroupChoice = "__new__";

type LinkUsersDialogProps = {
  selections: LinkUserSelection[];
  linking: boolean;
  error?: string;
  onClose: () => void;
  onLink: (input: LinkUsersInput) => void;
  onDirtyChange?: (dirty: boolean) => void;
};

function LinkUsersDialog({ selections, linking, error = "", onClose, onLink, onDirtyChange }: LinkUsersDialogProps) {
  const confirmation = useConfirmationDialog();
  const targets = useMemo(() => linkTargetGroups(selections), [selections]);
  const chooseTarget = needsLinkTargetChoice(selections, targets);
  const [targetChoice, setTargetChoice] = useState(newGroupChoice);
  const [leaderKey, setLeaderKey] = useState("");
  const initialTargetChoice = targets[0]?.id || newGroupChoice;
  const initialLeaderKey = preferredLinkLeaderKey(selections);

  useEffect(() => {
    setTargetChoice(initialTargetChoice);
    setLeaderKey(initialLeaderKey);
  }, [initialLeaderKey, initialTargetChoice, selections]);

  const dirty = targetChoice !== initialTargetChoice || leaderKey !== initialLeaderKey;
  useDirtyChange(selections.length >= 2, dirty, onDirtyChange);

  if (selections.length < 2) return null;

  const createsNewGroup = !chooseTarget || targetChoice === newGroupChoice;

  function submit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    onLink({
      selections,
      targetGroupId: createsNewGroup ? undefined : targetChoice,
      leaderKey: createsNewGroup ? leaderKey : undefined,
    });
  }

  async function requestClose() {
    if (linking) return;
    if (!dirty) {
      onClose();
      return;
    }
    const confirmed = await confirmation.confirm({
      title: "Associazione non completata",
      description: "Chiudere e perdere il gruppo o il leader scelto?",
      confirmLabel: "Abbandona associazione",
      tone: "danger",
    });
    if (confirmed) onClose();
  }

  return (
    <>
    <DialogBackdrop className="users-dialog-backdrop" dismissible={!linking} onDismiss={() => void requestClose()}>
      <form className="users-link-dialog" onSubmit={submit} role="dialog" aria-modal="true" aria-labelledby="link-users-title">
        <header>
          <h2 id="link-users-title" className="contextual-heading" title="Associazione utenti">Associa {selections.length} utenti</h2>
          <p>Gli utenti associati condivideranno le regole di sincronizzazione del gruppo.</p>
        </header>

        {error ? <p className="users-dialog-error" role="alert">{error}</p> : null}
        {hasDifferentLinkNames(selections) ? <p className="users-link-warning">I nomi selezionati non coincidono. Verifica che appartengano alla stessa persona prima di continuare.</p> : null}

        <section className="users-link-selection" aria-label="Utenti selezionati">
          {selections.map(({ user, groupName }) => <span key={userSelectionKey(user)}><strong>{user.name}</strong><small><ServerIdentity name={user.server_alias || user.server_name} icon={user.server_icon} color={user.server_icon_color} iconStyle={user.server_icon_style} size={11} /> · {groupName}</small></span>)}
        </section>

        {chooseTarget ? (
          <fieldset disabled={linking}>
            <legend>Gruppo di destinazione</legend>
            <div className="users-link-choice-list">
              <label className="users-link-choice">
                <input type="radio" name="link-target" value={newGroupChoice} checked={targetChoice === newGroupChoice} onChange={() => setTargetChoice(newGroupChoice)} />
                <span><strong>Crea nuovo gruppo</strong><small>Scegli il leader qui sotto.</small></span>
              </label>
              {targets.map((target) => (
                <label key={target.id} className="users-link-choice">
                  <input type="radio" name="link-target" value={target.id} checked={targetChoice === target.id} onChange={() => setTargetChoice(target.id)} />
                  <span><strong>Usa gruppo: {target.name}</strong><small>Conserva il leader e le impostazioni del gruppo scelto.</small></span>
                </label>
              ))}
            </div>
          </fieldset>
        ) : null}

        {createsNewGroup ? (
          <fieldset disabled={linking}>
            <legend>Leader del nuovo gruppo</legend>
            <div className="users-link-choice-list">
              {selections.map(({ user }) => {
                const key = userSelectionKey(user);
                return <label key={key} className="users-link-choice"><input type="radio" name="link-leader" value={key} checked={leaderKey === key} onChange={() => setLeaderKey(key)} /><span><strong>{user.name}</strong><small><ServerIdentity name={user.server_alias || user.server_name} icon={user.server_icon} color={user.server_icon_color} iconStyle={user.server_icon_style} size={11} />{user.is_user_disabled || user.is_disabled ? " · Account disabilitato" : ""}</small></span></label>;
              })}
            </div>
          </fieldset>
        ) : null}

        <footer>
          <Button type="button" variant="ghost" onClick={() => void requestClose()} disabled={linking}>Annulla</Button>
          <Button type="submit" variant="primary" disabled={linking || (createsNewGroup && !leaderKey)}>{linking ? "Associazione..." : "Associa utenti"}</Button>
        </footer>
      </form>
    </DialogBackdrop>
    {confirmation.dialog}
    </>
  );
}

export { LinkUsersDialog };
