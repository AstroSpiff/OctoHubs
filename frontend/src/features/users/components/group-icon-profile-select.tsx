import { iconBindingKey, userIconTargetId } from "@/features/user-icons/presentation";
import type { IconProfile } from "@/features/user-icons/types";
import type { EmbyUserGroup } from "@/features/users/types";

type GroupIconProfileSelectProps = {
  group: EmbyUserGroup;
  profiles: IconProfile[];
  bindings: Record<string, string>;
  saving: boolean;
  onChange: (profileId: string) => void;
};

function GroupIconProfileSelect({ group, profiles, bindings, saving, onChange }: GroupIconProfileSelectProps) {
  const currentProfileId = groupProfileId(group, bindings);

  return (
    <label className="group-icon-profile-select">
      <span>Icone</span>
      <select aria-label={`Profilo icona per ${group.name}`} value={currentProfileId} onChange={(event) => onChange(event.target.value)} disabled={saving}>
        {currentProfileId === "__mixed__" ? <option value="__mixed__" disabled>Profili diversi</option> : null}
        <option value="">Profilo icona...</option>
        {profiles.map((profile) => <option key={profile.id} value={profile.id}>{profile.label}</option>)}
      </select>
    </label>
  );
}

function groupProfileId(group: EmbyUserGroup, bindings: Record<string, string>) {
  if (group.is_linked) return bindings[iconBindingKey("group", group.id)] || "";

  const profileIds = group.users
    .map((user) => bindings[iconBindingKey("user", userIconTargetId(user))] || "")
    .filter(Boolean);
  const uniqueProfileIds = [...new Set(profileIds)];
  if (uniqueProfileIds.length > 1) return "__mixed__";
  return uniqueProfileIds[0] || "";
}

export { GroupIconProfileSelect };
