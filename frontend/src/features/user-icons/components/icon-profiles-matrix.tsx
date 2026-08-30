import { Camera, LoaderCircle, Pencil, Plus, Trash2 } from "@/components/ui/icons";

import { Button } from "@/components/ui/button";
import { useWorkspaceCapabilities } from "@/features/session/workspace-capabilities-context";
import { iconImageUrl } from "@/features/user-icons/presentation";
import type { IconProfile, UserIconConfig } from "@/features/user-icons/types";
import type { EmbyUserServer } from "@/features/users/types";

type IconProfilesMatrixProps = {
  config: UserIconConfig;
  servers: EmbyUserServer[];
  revision: number;
  changingProfileId?: string;
  changingRule?: { profileId: string; serverId: string };
  profileError?: (profile: IconProfile) => string | undefined;
  ruleError?: (profileId: string, serverId: string) => string | undefined;
  showHeader?: boolean;
  onCreate: () => void;
  onEdit: (profile: IconProfile) => void;
  onDeleteProfile: (profile: IconProfile) => void;
  onUpload: (profileId: string, serverId: string, file: File) => void;
  onDeleteRule: (profileId: string, serverId: string) => void;
};

function IconProfilesMatrix({ config, servers, revision, changingProfileId, changingRule, profileError, ruleError, showHeader = true, onCreate, onEdit, onDeleteProfile, onUpload, onDeleteRule }: IconProfilesMatrixProps) {
  return (
    <section className="user-icons-profiles" aria-labelledby="icon-profiles-title">
      {showHeader ? <header>
        <div>
          <h4 id="icon-profiles-title" className="contextual-heading" title="Template grafici">Profili icona</h4>
          <p>Carica un&apos;immagine per ogni server. L&apos;immagine selezionata viene applicata quando il profilo è associato.</p>
        </div>
        <Button type="button" requiresWriteAccess variant="primary" size="compact" onClick={onCreate}><Plus size={16} aria-hidden="true" />Nuovo profilo</Button>
      </header> : null}
      <div
        className="user-icons-matrix-scroll"
        role="region"
        tabIndex={0}
        aria-label="Matrice profili icona per server. Scorri orizzontalmente per vedere tutti i server."
      >
        <table className="user-icons-matrix">
          <thead><tr><th>Profilo</th>{servers.map((server) => <th key={server.id}>{server.name}</th>)}</tr></thead>
          <tbody>{config.profiles.map((profile) => <ProfileRow key={profile.id} profile={profile} servers={servers} matrix={config.matrix[profile.id] || {}} revision={revision} changing={changingProfileId === profile.id || changingRule?.profileId === profile.id} changingRule={changingRule} error={profileError?.(profile)} ruleError={ruleError} onEdit={onEdit} onDeleteProfile={onDeleteProfile} onUpload={onUpload} onDeleteRule={onDeleteRule} />)}</tbody>
        </table>
        {!config.profiles.length ? <p className="user-icons-empty">Non ci sono ancora profili icona.</p> : null}
      </div>
    </section>
  );
}

function ProfileRow({ profile, servers, matrix, revision, changing, changingRule, error, ruleError, onEdit, onDeleteProfile, onUpload, onDeleteRule }: { profile: IconProfile; servers: EmbyUserServer[]; matrix: Record<string, string>; revision: number; changing: boolean; changingRule?: { profileId: string; serverId: string }; error?: string; ruleError?: IconProfilesMatrixProps["ruleError"]; onEdit: (profile: IconProfile) => void; onDeleteProfile: (profile: IconProfile) => void; onUpload: (profileId: string, serverId: string, file: File) => void; onDeleteRule: (profileId: string, serverId: string) => void }) {
  return (
    <tr>
      <th scope="row">
        <div className="user-icons-profile-name">
          <span><strong>{profile.label}</strong><small>{profile.is_group_profile ? "Profilo gruppo" : "Profilo utente"}</small>{error ? <small className="user-icons-profile-error" role="alert">{error}</small> : null}</span>
          <span>
            <Button type="button" requiresWriteAccess variant="ghost" size="icon" title="Modifica profilo" aria-label={`Modifica profilo ${profile.label}`} onClick={() => onEdit(profile)} disabled={changing}><Pencil size={15} aria-hidden="true" /></Button>
            <Button type="button" requiresWriteAccess variant="ghost" size="icon" title="Elimina profilo" aria-label={`Elimina profilo ${profile.label}`} onClick={() => onDeleteProfile(profile)} disabled={changing}><Trash2 size={15} aria-hidden="true" /></Button>
          </span>
        </div>
      </th>
      {servers.map((server) => <IconRuleCell key={server.id} profile={profile} server={server} iconPath={matrix[server.id]} revision={revision} changing={changingRule?.profileId === profile.id && changingRule.serverId === server.id} error={ruleError?.(profile.id, server.id)} onUpload={onUpload} onDelete={onDeleteRule} />)}
    </tr>
  );
}

function IconRuleCell({ profile, server, iconPath, revision, changing, error, onUpload, onDelete }: { profile: IconProfile; server: EmbyUserServer; iconPath?: string; revision: number; changing: boolean; error?: string; onUpload: (profileId: string, serverId: string, file: File) => void; onDelete: (profileId: string, serverId: string) => void }) {
  const { canMutate } = useWorkspaceCapabilities();
  const inputId = `icon-file-${profile.id}-${server.id}`;

  return (
    <td>
      <div className="user-icons-rule-cell">
        {canMutate ? <input id={inputId} className="sr-only" type="file" accept="image/png,image/jpeg,image/webp" disabled={changing} onChange={(event) => { const file = event.target.files?.[0]; if (file) onUpload(profile.id, server.id, file); event.currentTarget.value = ""; }} /> : null}
        {canMutate ? iconPath ? <label className="user-icons-image-button" htmlFor={inputId} title={changing ? "Operazione in corso" : "Sostituisci immagine"} aria-disabled={changing}><img src={iconImageUrl(iconPath, revision)} alt={`Icona ${profile.label} per ${server.name}`} /></label> : <label className="user-icons-image-placeholder" htmlFor={inputId} title={changing ? "Operazione in corso" : "Carica immagine"} aria-disabled={changing}><Camera size={18} aria-hidden="true" /></label> : iconPath ? <span className="user-icons-image-button"><img src={iconImageUrl(iconPath, revision)} alt={`Icona ${profile.label} per ${server.name}`} /></span> : <span aria-label="Nessuna immagine">—</span>}
        {changing ? <span className="user-icons-rule-progress" role="status" aria-label="Operazione immagine in corso"><LoaderCircle className="animate-spin" size={15} aria-hidden="true" /></span> : iconPath ? <Button type="button" requiresWriteAccess variant="ghost" size="icon" title="Rimuovi immagine" aria-label={`Rimuovi immagine ${profile.label} su ${server.name}`} onClick={() => onDelete(profile.id, server.id)}><Trash2 size={14} aria-hidden="true" /></Button> : null}
        {error ? <small className="user-icons-rule-error" role="alert">{error}</small> : null}
      </div>
    </td>
  );
}

export { IconProfilesMatrix };
