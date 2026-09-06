import { RefreshCw } from "@/components/ui/icons";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import { useConfirmationDialog } from "@/components/ui/use-confirmation-dialog";
import { WorkspaceHeading } from "@/components/ui/workspace-heading";
import { IconProfileDialog } from "@/features/user-icons/components/icon-profile-dialog";
import { IconProfilesMatrix } from "@/features/user-icons/components/icon-profiles-matrix";
import type { IconProfile } from "@/features/user-icons/types";
import type { UserIconsController } from "@/features/user-icons/use-user-icons";
import type { EmbyUserServer } from "@/features/users/types";

function UserIconManagementSection({ icons, servers, onDirtyChange }: { icons: UserIconsController; servers: EmbyUserServer[]; onDirtyChange?: (dirty: boolean) => void }) {
  const confirmation = useConfirmationDialog();
  const [dialogProfile, setDialogProfile] = useState<IconProfile | null | undefined>(undefined);
  const [profileDialogOpen, setProfileDialogOpen] = useState(false);
  const config = icons.config.data || { profiles: [], matrix: {}, bindings: {} };
  const revision = icons.config.dataUpdatedAt;
  const profileDialogError = icons.profile.error
    && icons.profile.variables?.id === dialogProfile?.id
    ? icons.profile.error.message
    : undefined;

  function editProfile(profile?: IconProfile) {
    setDialogProfile(profile || null);
    setProfileDialogOpen(true);
  }

  function saveProfile(input: { id?: string; label: string; isGroupProfile: boolean }) {
    icons.profile.mutate(input, { onSuccess: () => setProfileDialogOpen(false) });
  }

  async function deleteProfile(profile: IconProfile) {
    if (!await confirmation.confirm({ title: "Elimina profilo icona", description: `Eliminare il profilo icona “${profile.label}”?`, confirmLabel: "Elimina profilo", tone: "danger" })) return;
    icons.removeProfile.mutate(profile.id);
  }

  function uploadRule(profileId: string, serverId: string, file: File) {
    icons.rule.mutate({ profileId, serverId, file });
  }

  async function deleteRule(profileId: string, serverId: string) {
    if (!await confirmation.confirm({ title: "Rimuovi immagine profilo", description: "Rimuovere questa immagine dal profilo? L'immagine già presente in Emby non viene modificata.", confirmLabel: "Rimuovi immagine", tone: "danger" })) return;
    icons.removeRule.mutate({ profileId, serverId });
  }

  return (
    <section id="icon-management-card" className="users-icon-management" tabIndex={-1} aria-labelledby="icon-management-title">
      <WorkspaceHeading
        actionsClassName="users-icon-management-actions"
        level="subsection"
        titleId="icon-management-title"
        title="Gestione icone utente"
        description="Gestisci i template grafici e le regole di assegnazione per gruppi e utenti singoli."
        actions={<>
          <Button type="button" requiresWriteAccess variant="primary" size="compact" onClick={() => editProfile()}>Nuovo profilo</Button>
          <Button type="button" variant="secondary" size="icon" title="Aggiorna profili icona" aria-label="Aggiorna profili icona" onClick={() => void icons.config.refetch()} disabled={icons.config.isFetching}><RefreshCw size={16} className={icons.config.isFetching ? "animate-spin" : ""} aria-hidden="true" /></Button>
        </>}
      />
      {icons.config.error ? <div className="inline-alert inline-alert--error" role="alert">{icons.config.error.message}</div> : null}
      <IconProfilesMatrix config={config} servers={servers} revision={revision} pendingProfileKeys={icons.profileOperations.pendingKeys} pendingRuleKeys={icons.ruleOperations.pendingKeys} profileErrors={icons.profileOperations.errors} ruleErrors={icons.ruleOperations.errors} showHeader={false} onCreate={() => editProfile()} onEdit={editProfile} onDeleteProfile={(profile) => void deleteProfile(profile)} onUpload={uploadRule} onDeleteRule={(profileId, serverId) => void deleteRule(profileId, serverId)} />
      <IconProfileDialog open={profileDialogOpen} profile={dialogProfile} saving={icons.profile.isPending} error={profileDialogError} onClose={() => setProfileDialogOpen(false)} onSave={saveProfile} onDirtyChange={onDirtyChange} />
      {confirmation.dialog}
    </section>
  );
}

export { UserIconManagementSection };
