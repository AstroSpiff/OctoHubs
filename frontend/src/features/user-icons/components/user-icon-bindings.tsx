import { Link2 } from "@/components/ui/icons";

import { iconBindingKey, userIconTargetId } from "@/features/user-icons/presentation";
import type { IconProfile, UserIconConfig } from "@/features/user-icons/types";
import type { EmbyUser, EmbyUserGroup } from "@/features/users/types";

type UserIconBindingsProps = {
  groups: EmbyUserGroup[];
  config: UserIconConfig;
  search: string;
  savingKey?: string;
  onChange: (targetType: "group" | "user", targetId: string, profileId: string) => void;
};

function UserIconBindings({ groups, config, search, savingKey, onChange }: UserIconBindingsProps) {
  const needle = search.trim().toLocaleLowerCase("it");
  const visibleGroups = groups.filter((group) => group.name.toLocaleLowerCase("it").includes(needle) || group.users.some((user) => user.name.toLocaleLowerCase("it").includes(needle) || user.server_name.toLocaleLowerCase("it").includes(needle)));

  return (
    <section className="user-icon-bindings" aria-labelledby="user-icon-bindings-title">
      <header><div><h4 id="user-icon-bindings-title" className="contextual-heading" title="Assegnazioni"><Link2 size={18} aria-hidden="true" />Icone su gruppi e utenti</h4><p>Un profilo di gruppo usa l&apos;icona del server del leader per tutti i membri associati.</p></div></header>
      <div className="user-icon-binding-list">
        {visibleGroups.map((group) => group.is_linked ? <BindingRow key={`group:${group.id}`} label={group.name} detail={`${group.users.length} utenti associati`} targetType="group" targetId={group.id} profiles={config.profiles} bindings={config.bindings} saving={savingKey === iconBindingKey("group", group.id)} onChange={onChange} /> : group.users.map((user) => <UserBindingRow key={`user:${user.server_id}:${user.user_id}`} user={user} profiles={config.profiles} bindings={config.bindings} saving={savingKey === iconBindingKey("user", userIconTargetId(user))} onChange={onChange} />))}
      </div>
      {!visibleGroups.length ? <p className="user-icons-empty">Nessun gruppo o utente corrisponde alla ricerca.</p> : null}
    </section>
  );
}

function UserBindingRow({ user, profiles, bindings, saving, onChange }: { user: EmbyUser; profiles: IconProfile[]; bindings: Record<string, string>; saving: boolean; onChange: UserIconBindingsProps["onChange"] }) {
  return <BindingRow label={user.name} detail={user.server_alias || user.server_name} targetType="user" targetId={userIconTargetId(user)} profiles={profiles} bindings={bindings} saving={saving} onChange={onChange} />;
}

function BindingRow({ label, detail, targetType, targetId, profiles, bindings, saving, onChange }: { label: string; detail: string; targetType: "group" | "user"; targetId: string; profiles: IconProfile[]; bindings: Record<string, string>; saving: boolean; onChange: UserIconBindingsProps["onChange"] }) {
  const key = iconBindingKey(targetType, targetId);

  return <div className="user-icon-binding-row"><div><strong>{label}</strong><small>{detail}</small></div><label><span className="sr-only">Profilo icona per {label}</span><select value={bindings[key] || ""} onChange={(event) => onChange(targetType, targetId, event.target.value)} disabled={saving}><option value="">Nessun profilo</option>{profiles.map((profile) => <option key={profile.id} value={profile.id}>{profile.label}</option>)}</select></label></div>;
}

export { UserIconBindings };
